import html
import aiohttp
from io import BytesIO

from telegram import Update
from telegram.ext import ContextTypes

from utils.http import get_http_session
from utils.config import ZHIPU_API_KEY

ZHIPU_IMAGE_URL = "https://open.bigmodel.cn/api/paas/v4/images/generations"
ZHIPU_IMAGE_MODEL = "cogview-3-flash"
ZHIPU_IMAGE_SIZE = "1024x1024"


async def zhipu_generate_image(prompt: str) -> BytesIO:
    if not ZHIPU_API_KEY:
        raise RuntimeError("ZHIPU_API_KEY belum diset")

    payload = {
        "model": ZHIPU_IMAGE_MODEL,
        "prompt": prompt,
        "size": ZHIPU_IMAGE_SIZE,
    }

    headers = {
        "Authorization": f"Bearer {ZHIPU_API_KEY}",
        "Content-Type": "application/json",
    }

    session = await get_http_session()
    async with session.post(
        ZHIPU_IMAGE_URL,
        headers=headers,
        json=payload,
        timeout=aiohttp.ClientTimeout(total=60),
    ) as resp:
        if resp.status != 200:
            raise RuntimeError(await resp.text())
        data = await resp.json()

    image_url = data["data"][0]["url"]

    async with session.get(image_url) as img_resp:
        if img_resp.status != 200:
            raise RuntimeError("Gagal download gambar")
        content = await img_resp.read()

    bio = BytesIO(content)
    bio.name = "zhipu.png"
    bio.seek(0)
    return bio


async def zhipuimg_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    if not context.args:
        return await msg.reply_text(
            "<b>🎨 Zhipu Image</b>\n\n"
            "Contoh:\n"
            "<code>/glmimg kucing lucu di jendela, cahaya matahari</code>",
            parse_mode="HTML"
        )

    prompt = " ".join(context.args).strip()

    status = await msg.reply_text(
        "🎨 <i>Lagi bikin gambar...</i>",
        parse_mode="HTML"
    )

    try:
        img = await zhipu_generate_image(prompt)
        await status.delete()
        await msg.reply_photo(photo=img)

    except Exception as e:
        await status.edit_text(
            f"<b>❌ Gagal generate image</b>\n"
            f"<code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )