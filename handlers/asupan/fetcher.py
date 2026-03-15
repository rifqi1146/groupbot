import random
import aiohttp
from utils.http import get_http_session
from .constants import DEFAULT_ASUPAN_KEYWORDS


async def fetch_asupan_tikwm(keyword: str | None = None):
    query = keyword.strip() if keyword else random.choice(DEFAULT_ASUPAN_KEYWORDS)

    api_url = "https://www.tikwm.com/api/feed/search"
    payload = {
        "keywords": query,
        "count": 20,
        "cursor": 0,
        "region": "ID",
    }

    session = await get_http_session()
    async with session.post(
        api_url,
        json=payload,
        timeout=aiohttp.ClientTimeout(total=15),
    ) as r:
        data = await r.json()

    if data.get("code") != 0:
        raise RuntimeError(f"TikWM API error: {data.get('msg')}")

    videos = data.get("data", {}).get("videos") or []
    if not videos:
        raise RuntimeError("Asupan kosong")

    return random.choice(videos)["play"]