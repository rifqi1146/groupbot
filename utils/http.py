import aiohttp
import logging
import json

logger = logging.getLogger(__name__)

_HTTP_SESSION: aiohttp.ClientSession | None = None


async def get_http_session():
    global _HTTP_SESSION
    if _HTTP_SESSION is None or _HTTP_SESSION.closed:
        _HTTP_SESSION = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60)
        )
    return _HTTP_SESSION


async def close_http_session():
    global _HTTP_SESSION
    if _HTTP_SESSION and not _HTTP_SESSION.closed:
        await _HTTP_SESSION.close()
        _HTTP_SESSION = None
        logger.info("HTTP session closed")


async def async_searcher(
    url: str,
    method: str = "GET",
    headers: dict | None = None,
    data: dict | None = None,
    re_json: bool = False,
    text: bool = False,
):
    session = await get_http_session()

    try:
        async with session.request(
            method,
            url,
            headers=headers,
            json=data if method != "GET" else None,
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status} for {url}")

            if re_json:
                return await resp.json(content_type=None)

            if text:
                return await resp.text()

            return await resp.read()

    except Exception as e:
        logger.error("async_searcher error: %s", e)
        raise
