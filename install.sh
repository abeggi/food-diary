#!/usr/bin/env bash
# install.sh – deploy food-diary on Ubuntu LXC
# Run as root: bash install.sh
set -euo pipefail

APP_DIR="/opt/food-diary"
DATA_DIR="$APP_DIR/data"
SERVICE="food-diary"
PORT=8080

echo "==> Creating directories..."
mkdir -p "$APP_DIR" "$DATA_DIR"

echo "==> Copying app files..."
cp -r . "$APP_DIR/"
chown -R www-data:www-data "$APP_DIR"
chmod -R 750 "$APP_DIR"
chmod 770 "$DATA_DIR"

echo "==> Creating Python venv..."
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

echo "==> Installing systemd service..."
cp "$APP_DIR/food-diary.service" "/etc/systemd/system/${SERVICE}.service"
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"

echo ""
echo "✓ Food Diary avviato su http://$(hostname -I | awk '{print $1}'):${PORT}"
echo "  Logs: journalctl -u ${SERVICE} -f"
