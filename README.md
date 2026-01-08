[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)](https://www.python.org/)
[![python-telegram-bot](https://img.shields.io/badge/python--telegram--bot-22.5-blue?logo=telegram)](https://github.com/python-telegram-bot/python-telegram-bot)
[![License](https://img.shields.io/badge/License-GPLv3-green)](https://www.gnu.org/licenses/gpl-3.0.html)

gatau bg mau nulis apa


### Installation
```
apt install -y \
    python3 \
    python3-venv \
    python3-pip \
    git \
    ffmpeg \
    tesseract-ocr
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
```
nano .env
```
```
BOT_TOKEN=
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
GEMINI_API_URL=https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_API_KEY}
GROQ_API_KEY=
BOT_OWNER_ID=
LOG_CHAT_ID=
OPENROUTER_API_KEY=
```
```
source .env
```
```
python bot.py
```



## 🙏 Credits

This project was developed using ideas and architectural references from:

- Moon Userbot (GPL-3.0)  
  https://github.com/The-MoonTg-project/Moon-Userbot

Special thanks to **Pikachu** for the inspiration behind the *asupan* feature.  
Telegram channel: https://t.me/pikachukocak5
