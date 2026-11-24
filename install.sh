#!/usr/bin/env bash
# Installs the daemon for the current user and starts it on login. No root needed
# unless /dev/uinput is not writable (the script tells you what to run).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="$HOME/.local/share/controllercontroller"

python3 -m venv --system-site-packages "$dest/venv"   # system packages give the settings window GTK
"$dest/venv/bin/pip" install --quiet --upgrade "$here"

mkdir -p "$HOME/.config/systemd/user"
cp "$here/packaging/controllercontroller.service" "$HOME/.config/systemd/user/"
mkdir -p "$HOME/.local/share/applications"
sed "s|@PYTHON@|$dest/venv/bin/python|" "$here/packaging/io.github.lexsclav07.ControllerController.desktop" \
  > "$HOME/.local/share/applications/io.github.lexsclav07.ControllerController.desktop"
systemctl --user daemon-reload
systemctl --user enable controllercontroller.service
systemctl --user restart controllercontroller.service   # picks up updates; `enable --now` would leave an old daemon running

echo
if [ ! -w /dev/uinput ]; then
  echo "Almost done: /dev/uinput is not writable by you, so the daemon cannot start yet."
  echo "Run this once, then log out and in:"
  echo "  sudo cp $here/packaging/70-controllercontroller.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger"
else
  echo "Daemon installed and running (it also starts on login)."
fi
echo "Change buttons any time from the ControllerController app (or: $dest/venv/bin/python -m controllercontroller settings)."
echo "Next: load the browser extension from $here/extension (see README, 'Install')."
