#!/bin/sh
set -eu
# Run from an administrator-reviewed checkout with the three signed release assets.
exec /usr/bin/python3 -I "$(dirname "$0")/install_updater.py" "$@"
