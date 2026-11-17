# Developing osh-contrib

Contributor notes for the plugin monorepo. User-facing install
instructions live in [README.md](README.md).

## Releasing

Contrib tags mirror `osh` versions: tag `vX.Y.Z` marks the contrib state
tested against `osh` X.Y.Z, and users install it with the `@vX.Y.Z` ref
shown in the README. There is no separate versioning — the tag _is_ the
release.

To cut a release once the matching `osh` version is out:

```bash
# on master, with CI green
git tag -a vX.Y.Z -m "Contrib release for osh X.Y.Z"
git push origin vX.Y.Z
gh release create vX.Y.Z --generate-notes
```

Before tagging, make sure every plugin's `min_osh`/dependency floor in
its `pyproject.toml` reflects the `osh` APIs it actually uses — that is
what protects users who pair a contrib tag with an older `osh`.

Move the `Unreleased` entries in [CHANGELOG.md](CHANGELOG.md) under a
`## vX.Y.Z — YYYY-MM-DD` heading for the release.
