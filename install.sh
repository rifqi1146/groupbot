#!/usr/bin/env bash

set -e

echo "== GroupBot Installer =="
echo

if [[ $EUID -ne 0 ]]; then
  echo "❌ Please run as root (sudo ./install.sh)"
  exit 1
fi

echo "[1/5] Installing system dependencies..."
apt update
apt install -y \
  python3 \
  python3-venv \
  python3-pip \
  git \
  ffmpeg \
  tesseract-ocr \
  curl

echo
echo "[2/5] Installing Speedtest (Ookla)..."

if ! command -v speedtest >/dev/null 2>&1; then
  curl -L https://install.speedtest.net/app/cli/ookla-speedtest-1.2.0-linux-x86_64.tgz \
  | tar zx
  mv speedtest /usr/bin/speedtest
  chmod +x /usr/bin/speedtest
  echo "✔ Speedtest installed"
else
  echo "✔ Speedtest already installed"
fi

echo
echo "[3/5] Creating virtual environment..."

if [ ! -d "venv" ]; then
  python3 -m venv venv
fi

source venv/bin/activate

echo
echo "[4/5] Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

deactivate

echo
echo "[5/5] Done!"
echo
echo "Next steps:"
echo "1. Copy .env.example to .env"
echo "2. nano .env"
echo "2. Fill your BOT_TOKEN and API keys"
echo "3. Run:"
echo "   python bot.py"
echo
echo "Happy 🚀"