#!/usr/bin/env bash
# install_service.sh — Install and enable the systemd service on Raspberry Pi
# Run as: sudo bash scripts/install_service.sh

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_SRC="$PROJECT_DIR/systemd/bot.service"
SERVICE_DEST="/etc/systemd/system/homebot.service"
SERVICE_NAME="homebot"

# Check running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Please run with sudo: sudo bash $0"
    exit 1
fi

# Check systemd service file exists
if [ ! -f "$SERVICE_SRC" ]; then
    echo "ERROR: Service file not found at $SERVICE_SRC"
    exit 1
fi

echo "==> Installing Home Automation Bot as systemd service"

# Update WorkingDirectory in the service file to match current path
sed "s|WorkingDirectory=.*|WorkingDirectory=$PROJECT_DIR|g" "$SERVICE_SRC" > "$SERVICE_DEST"
sed -i "s|ExecStart=.*|ExecStart=$PROJECT_DIR/venv/bin/python $PROJECT_DIR/src/main.py|g" "$SERVICE_DEST"
sed -i "s|EnvironmentFile=.*|EnvironmentFile=$PROJECT_DIR/.env|g" "$SERVICE_DEST"

echo "==> Service file written to $SERVICE_DEST"

# Enable and start
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo ""
echo "==> Service installed and started!"
echo ""
echo "Useful commands:"
echo "  Check status:  sudo systemctl status $SERVICE_NAME"
echo "  View logs:     sudo journalctl -u $SERVICE_NAME -f"
echo "  Stop bot:      sudo systemctl stop $SERVICE_NAME"
echo "  Disable boot:  sudo systemctl disable $SERVICE_NAME"
