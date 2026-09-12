#!/bin/sh
# Run each plugin's test suite in its own pytest process — plugins are
# self-contained, so their tests run independently — followed by the
# repo-level tests. Extra arguments are passed to every pytest call.
set -e
cd "$(dirname "$0")"

for pkg_tests in osh_*/tests; do
    [ -d "$pkg_tests" ] || continue
    echo "=== ${pkg_tests%%/*}"
    python3 -m pytest "$pkg_tests" "$@"
done
if [ -d tests ]; then
    echo "=== tests"
    python3 -m pytest tests "$@"
fi
