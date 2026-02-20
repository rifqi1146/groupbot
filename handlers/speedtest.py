import os
import json
import time
import asyncio
import subprocess
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from telegram import Update
from telegram.ext import ContextTypes

from utils.config import OWNER_ID
from utils.fonts import get_font


#speedtest
IMG_W, IMG_H = 900, 520

#util
def run_speedtest():
    p = subprocess.run(
        [
            "speedtest",
            "--accept-license",
            "--accept-gdpr",
            "-f", "json"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if p.returncode != 0:
        raise RuntimeError(f"Speedtest failed: {p.stderr.strip()}")

    out = p.stdout.strip()

    start = out.find("{")
    end = out.rfind("}") + 1

    if start == -1 or end == -1:
        raise RuntimeError("Invalid speedtest output (no JSON found)")

    try:
        return json.loads(out[start:end])
    except json.JSONDecodeError as e:
        raise RuntimeError(f"JSON parse error: {e}")

def draw_gauge(draw, cx, cy, r, value, max_val, label, unit):
    start = 135
    end = 405
    angle = start + (min(value, max_val) / max_val) * (end - start)

    # arc bg
    draw.arc(
        [cx-r, cy-r, cx+r, cy+r],
        start=start, end=end,
        fill=(60,60,60), width=18
    )
    # arc fg
    draw.arc(
        [cx-r, cy-r, cx+r, cy+r],
        start=start, end=angle,
        fill=(0,170,255), width=18
    )

    draw.text((cx, cy-10), f"{value:.1f}",
              fill="white", anchor="mm", font=FONT_BIG)
    draw.text((cx, cy+35), unit,
              fill=(180,180,180), anchor="mm", font=FONT_UNIT)
    draw.text((cx, cy+r-10), label,
              fill=(160,160,160), anchor="mm", font=FONT_LABEL)

#image generator
def generate_image(data):
    img = Image.new("RGB", (IMG_W, IMG_H), (18,18,18))
    draw = ImageDraw.Draw(img)

    # header
    draw.text((40, 30), "Speedtest",
              fill="white", font=FONT_TITLE)
    draw.text((40, 65), "by Ookla",
              fill=(0,170,255), font=FONT_SMALL)

    ping = data["ping"]["latency"]
    down = data["download"]["bandwidth"] * 8 / 1e6
    up   = data["upload"]["bandwidth"] * 8 / 1e6
    isp  = data["isp"]
    srv  = data["server"]["location"]

    # ping
    draw.text((IMG_W-40, 40),
              f"PING  {ping:.1f} ms",
              fill="white", anchor="ra", font=FONT_LABEL)

    # gauges
    draw_gauge(draw, 300, 300, 130, down, 500, "DOWNLOAD", "Mbps")
    draw_gauge(draw, 600, 300, 130, up,   200, "UPLOAD",   "Mbps")

    # footer
    draw.text((40, IMG_H-60),
              f"Server: {srv}",
              fill=(180,180,180), font=FONT_SMALL)
    draw.text((40, IMG_H-35),
              f"Provider: {isp}",
              fill=(180,180,180), font=FONT_SMALL)

    draw.text((IMG_W-40, IMG_H-35),
              time.strftime("%Y-%m-%d %H:%M:%S"),
              fill=(120,120,120), anchor="ra", font=FONT_SMALL)

    bio = BytesIO()
    bio.name = "speedtest.png"
    img.save(bio, "PNG")
    bio.seek(0)
    return bio

# =========================
# LOAD FONTS
# =========================
FONT_TITLE = get_font("DejaVuSans-Bold.ttf", 34)
FONT_BIG   = get_font("DejaVuSans-Bold.ttf", 44)
FONT_UNIT  = get_font("DejaVuSans.ttf", 18)
FONT_LABEL = get_font("DejaVuSans.ttf", 20)
FONT_SMALL = get_font("DejaVuSans.ttf", 16)

#cmd speedtest
async def speedtest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user

    if not msg or not user:
        return

    if user.id not in OWNER_ID:
        return

    status = await update.message.reply_text("Running Speedtest...")

    try:
        data = await asyncio.to_thread(run_speedtest)
        img = await asyncio.to_thread(generate_image, data)

        await update.message.reply_photo(
            photo=img,
            reply_to_message_id=update.message.message_id
        )
        await status.delete()

    except Exception as e:
        await status.edit_text(f"Failed: {e}")
        

