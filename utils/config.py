import os
from dotenv import load_dotenv

load_dotenv()

def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

def require_int_env(name: str) -> int:
    value = require_env(name)
    try:
        return int(value)
    except ValueError:
        raise RuntimeError(f"Environment variable {name} must be an integer")

#bot token
BOT_TOKEN = require_env("BOT_TOKEN")

#owner id
OWNER_ID = require_int_env("BOT_OWNER_ID")

#logchat id
LOG_CHAT_ID = require_int_env("LOG_CHAT_ID")

#gsearch & gemini
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODELS = {
    "flash": "gemini-2.5-flash",
    "pro": "gemini-2.5-pro",
    "lite": "gemini-2.0-flash-lite-001",
}

#open router api key
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_THINK = "openai/gpt-oss-120b:free"
OPENROUTER_IMAGE_MODEL = "bytedance-seed/seedream-4.5"

#groq
GROQ_KEY = os.getenv("GROQ_API_KEY")
GROQ_BASE = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_TIMEOUT = int(os.getenv("GROQ_TIMEOUT", "30"))
COOLDOWN = int(os.getenv("GROQ_COOLDOWN", "2"))
GROQ_MEMORY = {}
