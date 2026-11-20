#!/bin/sh
cd "$(dirname "$0")/.." || exit 1
for candidato in python3 python py; do
  if "$candidato" -c "import sys" >/dev/null 2>&1; then
    exec "$candidato" -m jarvis.guardas
  fi
done
echo "Guarda sem Python no PATH." >&2
exit 1
