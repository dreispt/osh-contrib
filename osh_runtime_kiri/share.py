"""Public ``kiri share`` for ``osh odoo --kiri-share``.

Two halves live here: :func:`start_share` — the ``osh`` side, which
spawns the supervisor, waits for the public URL and hands back a
:class:`ShareSession` whose ``close()`` ends the share — and ``main``,
the supervisor itself run as ``python -m osh_runtime_kiri.share``.

The supervisor runs ``kiri share <port> --json`` and reports one line
on its stdout — ``live <url>`` or ``error <message>`` — then stops
writing to that pipe. A second pipe is the lifeline: ``osh`` keeps the
write end (marked inheritable so an exec'd Odoo inherits it) and the
supervisor reads until EOF, which ends ``kiri`` — so the public link
never outlives the Odoo run.
"""

import json
import os
import select
import subprocess
import sys
import threading
import time
from pathlib import Path

import click

_TIMEOUT_ENV = "OSH_KIRI_SHARE_TIMEOUT"
_DEFAULT_TIMEOUT = 30.0
_KILL_GRACE = 3.0
_REAP_TIMEOUT = 5.0
_SIGNIN_HINT = "Sign in with `kiri share login` if needed."


class ShareSession:
    """A running supervised ``kiri share``.

    ``url`` is the public ``https://*.runkiri.cloud`` address;
    ``close()`` ends the share — the lifeline's write end is dropped so
    the supervisor terminates ``kiri`` and exits.
    """

    def __init__(self, url, proc, status_fd, lifeline_fd):
        self.url = url
        self._proc = proc
        self._status_fd = status_fd
        self._lifeline_fd = lifeline_fd
        self._closed = False

    def close(self):
        """End the share and reap the supervisor."""
        if self._closed:
            return
        self._closed = True
        _shutdown(self._proc, self._status_fd, self._lifeline_fd)


def start_share(argv, *, timeout=None):
    """Start ``kiri share`` under the supervisor; return a ShareSession.

    *argv* is the share command line (``["kiri", "share", "<port>",
    "--json", ...]``). Blocks until the share reports its public URL —
    at most *timeout* seconds (``OSH_KIRI_SHARE_TIMEOUT``, default 30) —
    and raises ``click.ClickException`` when the share fails or times
    out.
    """
    if os.name == "nt":
        raise click.ClickException("--kiri-share is not supported on Windows yet.")
    if timeout is None:
        timeout = _share_timeout()
    status_r, status_w = os.pipe()
    lifeline_r, lifeline_w = os.pipe()
    try:
        proc = _spawn_supervisor(argv, lifeline_r, status_w)
    finally:
        os.close(status_w)
        os.close(lifeline_r)
    # The write end must survive ``os.execvp`` into Odoo — the share ends
    # when the last process holding it exits.
    os.set_inheritable(lifeline_w, True)
    try:
        url = _await_status(proc, status_r, timeout)
    except BaseException:
        _shutdown(proc, status_r, lifeline_w)
        raise
    return ShareSession(url, proc, status_r, lifeline_w)


def _spawn_supervisor(argv, lifeline_fd, status_fd):
    """Spawn ``python -m osh_runtime_kiri.share`` in its own session.

    The supervisor's stdout is the status pipe; *lifeline_fd* — the
    read end — is inherited so it can watch for EOF. Its own session
    keeps it out of the terminal's foreground group, so Ctrl+C reaches
    Odoo, not the share.
    """
    env = dict(os.environ)
    package_dir = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = (
        f"{package_dir}{os.pathsep}{env['PYTHONPATH']}"
        if env.get("PYTHONPATH")
        else package_dir
    )
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "osh_runtime_kiri.share",
            "--watch-fd",
            str(lifeline_fd),
            "--",
            *argv,
        ],
        stdin=subprocess.DEVNULL,
        stdout=status_fd,
        pass_fds=(lifeline_fd,),
        start_new_session=True,
        env=env,
    )


def _await_status(proc, status_fd, timeout):
    """Read the supervisor's one status line; return the public URL.

    The supervisor reports exactly one line — ``live <url>`` or
    ``error <message>`` — within *timeout* seconds.
    """
    deadline = time.monotonic() + timeout
    data = b""
    while b"\n" not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _status_error(proc, f"timed out after {timeout:g}s")
        ready, _, _ = select.select([status_fd], [], [], remaining)
        if not ready:
            raise _status_error(proc, f"timed out after {timeout:g}s")
        chunk = os.read(status_fd, 4096)
        if not chunk:
            raise _status_error(proc, "exited before reporting a URL")
        data += chunk
        if len(data) > 65536:
            raise _status_error(proc, "reported an oversized status line")
    line = data.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
    kind, _, message = line.partition(" ")
    if kind == "live" and message:
        return message
    if kind == "error" and message:
        raise click.ClickException(f"{message}\n{_SIGNIN_HINT}")
    raise click.ClickException(
        f"Kiri share reported an unexpected status: {line or '<empty>'}\n"
        f"{_SIGNIN_HINT}"
    )


def _status_error(proc, reason):
    """Build the ClickException for a share that never went live."""
    detail = f"Kiri share {reason}."
    rc = proc.poll()
    if rc is not None:
        detail += f" (supervisor exited with status {rc})"
    return click.ClickException(f"{detail}\n{_SIGNIN_HINT}")


def _shutdown(proc, status_fd, lifeline_fd):
    """End a share attempt: drop the lifeline, reap the supervisor."""
    try:
        os.close(lifeline_fd)
    except OSError:
        pass
    try:
        proc.wait(timeout=_REAP_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    try:
        os.close(status_fd)
    except OSError:
        pass


def _share_timeout():
    """Live-wait timeout in seconds: ``OSH_KIRI_SHARE_TIMEOUT`` or 30."""
    try:
        return float(os.environ.get(_TIMEOUT_ENV, _DEFAULT_TIMEOUT))
    except ValueError:
        return _DEFAULT_TIMEOUT


def main(argv=None):
    """Supervisor entry point — ``python -m osh_runtime_kiri.share``."""
    args = list(sys.argv[1:] if argv is None else argv)
    watch_fd, command = _parse_args(args)
    if watch_fd is None or not command:
        raise SystemExit(
            "usage: python -m osh_runtime_kiri.share --watch-fd FD -- <command>"
        )
    _supervise(watch_fd, command)


def _parse_args(args):
    """Split ``--watch-fd N -- <command>`` into ``(fd, argv)``."""
    watch_fd = None
    command = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--watch-fd" and index + 1 < len(args):
            watch_fd = int(args[index + 1])
            index += 2
        elif arg == "--":
            command = args[index + 1 :]
            break
        else:
            index += 1
    return watch_fd, command


def _supervise(watch_fd, command):
    """Run *command*, report its status, end it when the lifeline ends."""
    kiri = subprocess.Popen(command, stdout=subprocess.PIPE, text=True, bufsize=1)
    threading.Thread(target=_watch_lifeline, args=(watch_fd, kiri), daemon=True).start()
    url = None
    last_line = ""
    for line in kiri.stdout:
        line = line.strip()
        if not line:
            continue
        last_line = line
        event = _json_event(line)
        if event is None:
            continue
        kind = event.get("event")
        if kind == "live" and url is None:
            found = _first_https(event)
            if found is None:
                _report("error Kiri share went live but reported no URL")
                _stop(kiri)
                return
            url = found
            _report(f"live {url}")
        elif kind == "ended" and url is None:
            _report(f"error {event.get('message') or last_line}")
            _stop(kiri)
            return
    # kiri's stdout closed — the share process ended.
    kiri.wait()
    if url is None:
        _report(f"error {last_line or 'kiri share exited'}")


def _watch_lifeline(fd, proc):
    """Terminate *proc* when the lifeline pipe reaches EOF, then exit."""
    try:
        while os.read(fd, 4096):
            pass
    except OSError:
        pass
    _stop(proc)
    os._exit(0)


def _stop(proc):
    """Terminate *proc*, escalating to SIGKILL after a short grace."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=_KILL_GRACE)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _report(line):
    """Write the one status line, then detach stdout from the pipe."""
    try:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except OSError:
        pass
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
    except (OSError, ValueError):
        pass


def _json_event(line):
    """Parse a ``kiri share --json`` line into an event dict, or None."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) else None


def _first_https(value):
    """Return the first ``https://`` string inside a JSON value."""
    if isinstance(value, str):
        return value if value.startswith("https://") else None
    if isinstance(value, dict):
        for item in value.values():
            found = _first_https(item)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _first_https(item)
            if found is not None:
                return found
    return None


if __name__ == "__main__":
    main()
