from telegram import Update
from telegram.ext import ContextTypes
import aiohttp
import random

from utils.http import get_http_session
from utils.storage import load_json_file

NSFW_FILE = "data/nsfw_groups.json"


def _load_nsfw():
    return load_json_file(NSFW_FILE, {"groups": []})


ANIME_APIS = [
    # 1. WAIFU.PICS - Good reliable API with SFW and NSFW
    {
        "name": "Waifu.pics",
        "sfw_url": "https://api.waifu.pics/sfw/{tag}",
        "nsfw_url": "https://api.waifu.pics/nsfw/{tag}",
        "sfw_tags": ["waifu", "neko", "shinobu", "megumin", "bully", "cuddle", "cry", "hug", "awoo", "kiss", "lick", "pat", "smug", "bonk", "yeet", "blush", "smile", "wave", "highfive", "handhold", "nom", "bite", "glomp", "slap", "kill", "kick", "happy", "wink", "poke", "dance", "cringe"],
        "nsfw_tags": ["waifu", "neko", "trap", "blowjob"],
        "parse": lambda r: r.json()["url"] if r.status_code == 200 and "url" in r.json() else None
    },
    # 2. NEKOS.LIFE - Another good API for anime images
    {
        "name": "Nekos.life",
        "sfw_url": "https://nekos.life/api/v2/img/{tag}",
        "nsfw_url": "https://nekos.life/api/v2/img/{tag}",
        "sfw_tags": ["neko", "ngif", "smile", "waifu", "cuddle", "feed", "fox_girl", "lizard", "pat", "poke", "slap", "tickle"],
        "nsfw_tags": ["lewd", "ero", "blowjob", "tits", "boobs", "trap", "pussy", "cum", "hentai"],
        "parse": lambda r: r.json()["url"] if r.status_code == 200 and "url" in r.json() else None
    },
    # 3. WAIFU.IM - Great for higher quality anime images
    {
        "name": "Waifu.im",
        "sfw_url": "https://api.waifu.im/search?included_tags={tag}",
        "nsfw_url": "https://api.waifu.im/search?included_tags={tag}",
        "sfw_tags": ["maid", "waifu", "marin-kitagawa", "mori-calliope", "raiden-shogun", "oppai", "selfies", "uniform", "kamisato-ayaka"],
        "nsfw_tags": ["ass", "hentai", "milf", "oral", "paizuri", "ecchi", "ero"],
        "parse": lambda r: r.json()["images"][0]["url"] if r.status_code == 200 and "images" in r.json() and r.json()["images"] else None
    },
    # 4. NEKOBOT API - Popular anime image API with lots of NSFW
    {
        "name": "Nekobot",
        "sfw_url": "https://nekobot.xyz/api/image?type={tag}",
        "nsfw_url": "https://nekobot.xyz/api/image?type={tag}",
        "sfw_tags": ["neko", "kitsune", "waifu", "coffee"],
        "nsfw_tags": ["hentai", "ass", "boobs", "paizuri", "thigh", "hthigh", "anal", "hanal", "gonewild", "pgif", "4k", "lewdneko", "pussy", "holo", "lewdkitsune", "kemonomimi", "feet", "hfeet", "blowjob", "hmidriff", "hboobs", "tentacle"],
        "parse": lambda r: r.json()["message"] if r.status_code == 200 and "message" in r.json() else None
    },
    # 5. HMTAI API - Hentai/anime image API with tons of NSFW
    {
        "name": "HMTAI",
        "sfw_url": "https://hmtai.hatsunia.cfd/v2/sfw/{tag}",
        "nsfw_url": "https://hmtai.hatsunia.cfd/v2/nsfw/{tag}",
        "sfw_tags": ["wallpaper", "mobileWallpaper", "neko", "jahy", "slap", "lick", "depression"],
        "nsfw_tags": ["ass", "bdsm", "cum", "creampie", "manga", "femdom", "hentai", "incest", "masturbation", "public", "ero", "orgy", "elves", "yuri", "pantsu", "glasses", "cuckold", "blowjob", "boobjob", "foot", "thighs", "vagina", "ahegao", "uniform", "gangbang", "tentacles", "gif", "neko", "nsfwMobileWallpaper", "zettaiRyouiki"],
        "parse": lambda r: r.json() if r.status_code == 200 else None
    },
    # 6. WAIFU API
    {
        "name": "Waifu API",
        "sfw_url": "https://api.waifu.lu/v1/sfw/{tag}",
        "nsfw_url": "https://api.waifu.lu/v1/nsfw/{tag}",
        "sfw_tags": ["waifu", "neko", "uniform"],
        "nsfw_tags": ["waifu", "neko", "trap", "maid"],
        "parse": lambda r: r.json()["url"] if r.status_code == 200 and "url" in r.json() else None
    },
    # 7. ANIME-IMAGES-API - Another anime API
    {
        "name": "Anime Images",
        "sfw_url": "https://anime-api.hisoka17.repl.co/img/sfw/{tag}",
        "nsfw_url": "https://anime-api.hisoka17.repl.co/img/nsfw/{tag}",
        "sfw_tags": ["hug", "kiss", "slap", "wink", "pat", "kill", "cuddle", "punch", "waifu"],
        "nsfw_tags": ["hentai", "boobs", "lesbian"],
        "parse": lambda r: r.json()["url"] if r.status_code == 200 and "url" in r.json() else None
    },
    # 8. PICREW API - Better anime image API
    {
        "name": "Picrew API",
        "sfw_url": "https://api.waifu.pics/sfw/{tag}",
        "nsfw_url": "https://api.waifu.pics/nsfw/{tag}",
        "sfw_tags": ["waifu", "neko", "shinobu", "megumin", "bully", "cuddle", "cry", "hug", "awoo", "kiss", "lick", "pat", "smug", "bonk", "yeet", "blush", "smile", "wave", "highfive", "handhold", "nom", "bite", "glomp", "slap", "kill", "kick", "happy", "wink", "poke", "dance", "cringe"],
        "nsfw_tags": ["waifu", "neko", "trap", "blowjob"],
        "parse": lambda r: r.json()["url"] if r.status_code == 200 and "url" in r.json() else None
    },
    # 9. NEKOS.FUN - Anime API
    {
        "name": "Nekos Fun",
        "sfw_url": "https://api.nekos.fun/api/{tag}",
        "nsfw_url": "https://api.nekos.fun/api/{tag}",
        "sfw_tags": ["kiss", "lick", "hug", "baka", "cry", "poke", "smug", "slap", "tickle", "pat", "laugh", "feed", "cuddle"],
        "nsfw_tags": ["lesbian", "anal", "bj", "classic", "cum", "spank"],
        "parse": lambda r: r.json()["image"] if r.status_code == 200 and "image" in r.json() else None
    },
    # 10. ANIME-NEKO-API
    {
        "name": "Anime Neko",
        "sfw_url": "https://img-api.lioncube.fr/{tag}",
        "nsfw_url": "https://img-api.lioncube.fr/{tag}",
        "sfw_tags": ["neko", "kitsune", "waifu"],
        "nsfw_tags": ["hentai", "trap"],
        "parse": lambda r: r.json()["url"] if r.status_code == 200 and "url" in r.json() else None
    }
]

TAG_MAPPING = {
    "raiden": "raiden-shogun",
    "shogun": "raiden-shogun",
    "genshin": "genshin-impact",
    "ayaka": "kamisato-ayaka",
    "marin": "marin-kitagawa",
    "maid": "maid",
    "random": "waifu"
}

async def waifu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat = update.effective_chat
    if not msg or not chat:
        return

    nsfw = _load_nsfw()
    allow_nsfw = True
    if chat.type in ("group", "supergroup"):
        allow_nsfw = chat.id in nsfw["groups"]

    keyword = context.args[0].lower() if context.args else "random"
    tag = TAG_MAPPING.get(keyword, keyword)

    session = await get_http_session()
    random.shuffle(ANIME_APIS)

    for api in ANIME_APIS:
        try:
            tags = api["nsfw_tags"] if allow_nsfw else api["sfw_tags"]
            if not tags:
                continue

            use_tag = tag if tag in tags else random.choice(tags)

            # special case: waifu.im
            if api["name"] == "Waifu.im":
                params = {
                    "included_tags": use_tag,
                    "limit": 1
                }
                async with session.get(
                    "https://api.waifu.im/search",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    img_url = api["parse"](data)

            else:
                url = (api["nsfw_url"] if allow_nsfw else api["sfw_url"]).format(tag=use_tag)
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    img_url = api["parse"](data)

            if not img_url:
                continue

            caption = (
                f"💖 <b>Waifu</b>\n"
                f"🏷 Tag: <code>{use_tag}</code>\n"
                f"🌐 API: <b>{api['name']}</b>"
            )

            return await msg.reply_photo(
                photo=img_url,
                caption=caption,
                parse_mode="HTML"
            )

        except Exception as e:
            continue

    await msg.reply_text("❌ Semua API gagal 😭")
    
## Big thanks to @aenulrofik for this awesome feature ##
## And to me: Tg @IgnoredProjectXcl for the major enhancements ##
## Please don’t remove the credits — respect the creator! ##