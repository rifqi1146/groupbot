gatau bg mau nulis apa


### Installation

### Clone repository
```bash
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
ASUPAN_STARTUP_CHAT_ID=
OPENROUTER_API_KEY=
```
```
source .env
```
```
python bot.py
```
