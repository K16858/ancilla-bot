#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${ANCILLA_REPO_URL:-https://github.com/K16858/ancilla-bot.git}"
ROOT="${ANCILLA_ROOT:-$HOME/.local/share/ancilla}"
BIN_DIR="${ANCILLA_BIN_DIR:-$HOME/.local/bin}"

echo "Ancilla installer"
echo

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    exit 1
  fi
}

need git

PYTHON=""
for candidate in python3.12 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
      PYTHON="$candidate"
      break
    fi
  fi
done

if [[ -z "$PYTHON" ]]; then
  echo "Python 3.11+ is required."
  exit 1
fi

if ! "$PYTHON" -c 'import venv' >/dev/null 2>&1; then
  echo "python -m venv is not available."
  exit 1
fi

echo "Using Python: $PYTHON"
echo "Install root: $ROOT"

mkdir -p "$(dirname "$ROOT")"
if [[ -d "$ROOT/.git" ]]; then
  echo "Updating existing checkout..."
  git -C "$ROOT" pull --ff-only
else
  echo "Cloning repository..."
  git clone "$REPO_URL" "$ROOT"
fi

cd "$ROOT"
if [[ ! -d .venv ]]; then
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .

mkdir -p "$BIN_DIR"
LAUNCHER="$BIN_DIR/ancilla"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
ROOT="$ROOT"
export ANCILLA_ROOT="\$ROOT"
cd "\$ROOT" || exit 1
exec "\$ROOT/.venv/bin/ancilla" "\$@"
EOF
chmod +x "$LAUNCHER"

echo
echo "Installed launcher: $LAUNCHER"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    echo
    echo "Add to your shell profile (e.g. ~/.bashrc):"
    echo "  export PATH=\"$BIN_DIR:\$PATH\""
    ;;
esac

echo
echo "Next:"
echo "  ancilla install core"
echo "  ancilla setup"
echo "  ancilla start"
