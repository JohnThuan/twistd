#!/usr/bin/env sh
# Regenerate constraints.txt from a clean resolve of requirements-dev.txt (Linux, in Docker).
set -eu
cd "$(dirname "$0")/.."
: > constraints.txt
docker build --target test -t twistd-lockgen .
{
  echo "# Exact versions for reproducible builds. Regenerate with scripts/lock.sh."
  docker run --rm twistd-lockgen pip freeze --exclude-editable | grep -v '^pip==\|^setuptools==\|^wheel=='
} > constraints.txt.new
mv constraints.txt.new constraints.txt
echo "constraints.txt updated"
