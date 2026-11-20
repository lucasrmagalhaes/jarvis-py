#!/usr/bin/env bash
# Instalação do Jarvis no Linux e no macOS.
# Uso: ./scripts/instalar.sh [--wake]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WAKE=0
for arg in "$@"; do
  case "$arg" in
    --wake)
      WAKE=1
      ;;
    -h|--help)
      echo "Uso: ./scripts/instalar.sh [--wake]"
      echo "Cria o .venv, instala as dependências e roda python -m jarvis doctor."
      exit 0
      ;;
    *)
      echo "Argumento desconhecido: $arg"
      exit 2
      ;;
  esac
done

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "Não encontrei o Python. Instale o Python 3.11 ou mais novo e tente de novo."
  exit 1
fi

"$PYTHON" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if [[ "$WAKE" -eq 1 ]]; then
  python -m pip install -r requirements-wake-deps.txt
  python -m pip install --no-deps -r requirements-wake.txt
fi

set +e
python -m jarvis doctor
doctor_code=$?
set -e
if [[ "$doctor_code" -ne 0 ]]; then
  echo "O diagnóstico encontrou pendências. Os próximos passos continuam valendo."
fi

cat <<'EOF'

Próximos passos:
1. Ative o ambiente: source .venv/bin/activate
2. Se o checklist apontou o vault, rode: python -m jarvis.setup
3. Faça login no Claude Code uma vez: claude
4. Converse sem microfone: python -m jarvis.chat
5. Com microfone: python -m jarvis.main

O arquivo de exemplo das variáveis é .env.example.
Copie para ~/.jarvis/.env se quiser editar à mão. O .env não entra no git.
EOF
