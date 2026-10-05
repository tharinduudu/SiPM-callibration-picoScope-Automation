#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
DESKTOP_FILE="$HOME/.local/share/applications/glowcost-calibration.desktop"

if ! python3 -c 'import tkinter' >/dev/null 2>&1; then
  echo "Tkinter is required for the desktop interface."
  echo "Installing the Ubuntu python3-tk package requires sudo."
  sudo apt-get update
  sudo apt-get install -y python3-tk
fi

if ! python3 -m venv --help >/dev/null 2>&1; then
  echo "Python virtual-environment support is required."
  echo "Installing python3-venv requires sudo."
  sudo apt-get update
  sudo apt-get install -y python3-venv
fi

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  python3 -m venv "$ROOT/.venv"
fi

"$ROOT/.venv/bin/python" -m pip install --upgrade pip
"$ROOT/.venv/bin/python" -m pip install -r "$ROOT/requirements.txt"

mkdir -p "$(dirname "$DESKTOP_FILE")"
cat >"$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=gLOWCOST Calibration
Comment=SiPM and scintillator calibration tools
Exec=$HERE/launch.sh
Terminal=false
Categories=Science;Education;
EOF

chmod +x "$HERE/launch.sh" "$DESKTOP_FILE"
echo "Installed desktop launcher: $DESKTOP_FILE"
echo "The application can also be started with: $HERE/launch.sh"
