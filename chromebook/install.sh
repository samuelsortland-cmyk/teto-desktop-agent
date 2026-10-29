#!/usr/bin/env bash
# Teto for Chromebook - installer for the Chromebook's Linux side.
#   curl -fsSL https://raw.githubusercontent.com/samuelsortland-cmyk/teto-desktop-agent/main/chromebook/install.sh | bash
set -euo pipefail

REPO_URL="https://github.com/samuelsortland-cmyk/teto-desktop-agent.git"
DIR="$HOME/teto"
VENV="$DIR/.venv-chromebook"
say() { printf '\n\033[1;31m♪ Teto:\033[0m %s\n' "$*"; }

say "Hiii~ setting myself up on your Chromebook! This takes a few minutes the first time."

if ! command -v git >/dev/null || ! python3 -c "import venv, ensurepip" 2>/dev/null; then
  say "Installing Python and git (you may be asked for nothing - Linux on a Chromebook needs no password)..."
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3 python3-venv python3-pip git >/dev/null
fi

if [ -d "$DIR/.git" ]; then
  say "Updating my files..."
  git -C "$DIR" pull --ff-only --quiet origin main
else
  say "Downloading me..."
  git clone --quiet --depth 50 "$REPO_URL" "$DIR"
fi

say "Getting my brain ready (Claude Code)..."
python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$DIR/chromebook/requirements.txt"

# Start automatically whenever Linux is running.
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/teto-chromebook.service" <<UNIT
[Unit]
Description=Teto for Chromebook
After=network-online.target

[Service]
WorkingDirectory=$DIR/chromebook
ExecStart=$VENV/bin/python -m teto_cb
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now teto-chromebook.service >/dev/null 2>&1 || true
systemctl --user restart teto-chromebook.service || true

# A "Teto" app in the ChromeOS launcher: opening it starts Linux (and so Teto).
mkdir -p "$HOME/.local/share/applications" "$HOME/.local/share/icons"
cp "$DIR/chromebook/extension/icons/icon128.png" "$HOME/.local/share/icons/teto.png"
cat > "$HOME/.local/share/applications/teto.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Teto
Comment=Wake Teto up (then click her icon in Chrome)
Exec=bash -c 'systemctl --user start teto-chromebook.service; notify-send "Teto" "I am awake! Click my icon in Chrome to chat." 2>/dev/null || true'
Icon=$HOME/.local/share/icons/teto.png
Terminal=false
Categories=Utility;
DESK

sleep 2
if systemctl --user is-active --quiet teto-chromebook.service; then
  say "I'm running! ♪"
else
  say "I couldn't start in the background - you can start me with: cd $DIR/chromebook && $VENV/bin/python -m teto_cb"
fi

cat <<DONE

  Last step - add me to Chrome (one time):
    1. In Chrome, go to  chrome://extensions  and turn on "Developer mode" (top right).
    2. Click "Load unpacked", open "Linux files", then  teto > chromebook > extension,
       and click "Select".
    3. Click the puzzle-piece icon in Chrome's toolbar and pin "Teto for Chromebook".
    4. Click my icon - the chat opens on the side. Sign in with your Claude account and go!

  I update myself. If Linux restarts, open the "Teto" app from your launcher to wake me up.
DONE
