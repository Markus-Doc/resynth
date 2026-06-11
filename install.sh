#!/usr/bin/env bash
# RESYNTH installer for macOS and Linux.
#   curl -fsSL https://raw.githubusercontent.com/Markus-Doc/resynth/main/install.sh | bash
set -euo pipefail

REPO="https://github.com/Markus-Doc/resynth"
APP_DIR="${HOME}/.local/share/resynth/app"
WORK_DIR="${HOME}/RESYNTH"
BIN_DIR="${HOME}/.local/bin"

echo ""
echo "RESYNTH installer"
echo "-----------------"

if ! command -v python3 >/dev/null || [ "$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 11) else 0)')" != "1" ]; then
    echo "Python 3.11 or newer is required. Install it with your package manager, then re-run." >&2
    exit 1
fi
echo "Python: ok"

if ! command -v git >/dev/null; then
    echo "Git is required. Install it with your package manager, then re-run." >&2
    exit 1
fi
echo "Git: ok"

if [ -d "${APP_DIR}/.git" ]; then
    echo "Updating RESYNTH..."
    git -C "${APP_DIR}" pull --quiet
else
    echo "Downloading RESYNTH..."
    mkdir -p "$(dirname "${APP_DIR}")"
    git clone --quiet --depth 1 "${REPO}" "${APP_DIR}"
fi

echo "Installing (this takes a minute)..."
python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --quiet --upgrade pip
"${APP_DIR}/.venv/bin/pip" install --quiet -e "${APP_DIR}"

mkdir -p "${WORK_DIR}" "${BIN_DIR}"

cat > "${BIN_DIR}/resynth" <<EOF
#!/usr/bin/env bash
export RESYNTH_ROOT="${WORK_DIR}"
cd "${WORK_DIR}"
exec "${APP_DIR}/.venv/bin/resynth" "\$@"
EOF
chmod +x "${BIN_DIR}/resynth"

echo ""
echo "RESYNTH is installed."
echo "Launch the guided mode by running: resynth"
if ! echo "$PATH" | tr ':' '\n' | grep -qx "${BIN_DIR}"; then
    echo "Note: add ${BIN_DIR} to your PATH first."
fi
echo "Your research projects will live in ${WORK_DIR}"
