[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)](https://www.python.org/)
[![python-telegram-bot](https://img.shields.io/badge/python--telegram--bot-22.5-blue?logo=telegram)](https://github.com/python-telegram-bot/python-telegram-bot)
[![License](https://img.shields.io/badge/License-GPLv3-green)](https://www.gnu.org/licenses/gpl-3.0.html)

# Telegram Multi-Function Bot

A multi-function Telegram bot built with Python and `python-telegram-bot`, providing AI features, downloader utilities, moderation tools, networking commands, and additional group management features.

## Features

- AI chat and assistant commands
- Media downloader for multiple platforms
- Google search integration
- Networking and utility tools
- Moderation and administration features
- Group and verification features
- Entertainment and miscellaneous commands

## Quick Installation (Recommended)

The recommended installation method is to use the provided installer script:

```
git clone https://github.com/rifqi1146/groupbot.git
cd groupbot
sudo bash install.sh
```
## Manual Installation
```
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
```

```
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
sudo apt install -y nodejs
```

```
curl -fsSL https://deno.land/install.sh | sh
sudo ln -sf /root/.deno/bin/deno /usr/local/bin/deno
```

```
curl -L https://install.speedtest.net/app/cli/ookla-speedtest-1.2.0-linux-x86_64.tgz \
| tar zx

sudo mv speedtest /usr/bin/speedtest
sudo chmod +x /usr/bin/speedtest
```

### Clone repository
```
git clone https://github.com/rifqi1146/groupbot.git
```
```
cd groupbot
```
```
python3 -m venv venv
```
```
source venv/bin/activate
```
```
pip install --upgrade pip
```
```
pip install -r requirements.txt
```
## Environment Setup

```
nano .env
```
```
BOT_TOKEN=
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
GEMINI_API_URL="https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_API_KEY}"
GROQ_API_KEY=
GOOGLE_API_KEY=
GOOGLE_CSE_ID=
BOT_OWNER_ID=
LOG_CHAT_ID=
API_ID=
API_HASH=
SUPPORT_CH_ID=
SUPPORT_CH_LINK=
DONATE_URL=
QUOTE_API_URI="http://127.0.0.1:3000"
```
```
source .env
```
### Run Bot
```
python main.py
```

## Credits

This project uses and depends on the following tools and services:

- [Groq Cloud](https://console.groq.com/home)
- [Google Gemini](https://ai.google.dev/)
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- [gallery-dl](https://github.com/mikf/gallery-dl)
- [Sonzai Api](http://api.sonzaix.indevs.in)
- [TikWm](https://www.tikwm.com/)