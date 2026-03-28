#!/usr/bin/env bash
set -e

echo "== Installer =="
echo

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root:"
  echo "sudo bash install.sh"
  exit 1
fi

echo "[1/6] Installing system dependencies..."
apt update
apt install -y \
  python3 \
  python3-venv \
  python3-pip \
  git \
  ffmpeg \
  curl \
  unzip \
  build-essential \
  libjpeg-dev \
  zlib1g-dev \
  cmake \
  libssl-dev \
  gperf

echo
echo "[2/6] Installing Node.js..."

if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt install -y nodejs
  echo "✔ Node.js installed"
else
  echo "✔ Node.js already installed"
fi

echo
echo "[3/6] Installing Deno..."

if ! command -v deno >/dev/null 2>&1; then
  curl -fsSL https://deno.land/install.sh | sh
  ln -sf /root/.deno/bin/deno /usr/local/bin/deno
  echo "✔ Deno installed"
else
  echo "✔ Deno already installed"
fi

echo
echo "[4/6] Installing Speedtest Ookla..."

if ! command -v speedtest >/dev/null 2>&1; then
  ARCH=$(uname -m)

  case "$ARCH" in
    x86_64)
      SPEEDTEST_URL="https://install.speedtest.net/app/cli/ookla-speedtest-1.2.0-linux-x86_64.tgz"
      ;;
    aarch64|arm64)
      SPEEDTEST_URL="https://install.speedtest.net/app/cli/ookla-speedtest-1.2.0-linux-aarch64.tgz"
      ;;
    *)
      echo "Unsupported architecture: $ARCH"
      exit 1
      ;;
  esac

  curl -L "$SPEEDTEST_URL" | tar zx
  mv speedtest /usr/bin/speedtest
  chmod +x /usr/bin/speedtest

  echo "✔ Speedtest installed"
else
  echo "✔ Speedtest already installed"
fi

echo
read -rp "Do you want to build local Telegram Bot API? [Y/N]: " BUILD_LOCAL_BOT_API
BUILD_LOCAL_BOT_API=$(echo "$BUILD_LOCAL_BOT_API" | tr '[:lower:]' '[:upper:]')

if [[ "$BUILD_LOCAL_BOT_API" == "Y" ]]; then
  echo
  echo "[5/6] Building local Telegram Bot API..."

  if [ ! -d "telegram-bot-api" ]; then
    git clone --recursive https://github.com/tdlib/telegram-bot-api.git
  else
    echo "✔ telegram-bot-api source already exists"
  fi

  cd telegram-bot-api

  if [ ! -d "build" ]; then
    mkdir build
  fi

  cd build
  cmake -DCMAKE_BUILD_TYPE=Release ..
  cmake --build . --target install -j"$(nproc)"
  cd ../..

  echo "✔ Local Telegram Bot API build successfully"
else
  echo
  echo "[5/6] Skipping local Telegram Bot API build..."
fi

echo
echo "[6/6] Creating virtual environment..."

if [ ! -d "venv" ]; then
  python3 -m venv venv
fi

source venv/bin/activate

echo
echo "[7/7] Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

deactivate

echo
echo "Done!"
echo
echo "Next steps:"
echo "1. nano .env"
echo "2. Fill BOT_TOKEN and API keys"
if [[ "$BUILD_LOCAL_BOT_API" == "Y" ]]; then
  echo "3. If using local Bot API, also fill API_ID and API_HASH in .env"
fi
echo "4. Run:"
echo "   source venv/bin/activate"
echo "   python main.py"
echo
echo "Happy 🚀"