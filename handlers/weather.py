import time
import asyncio
import aiohttp

from telegram import Update
from telegram.ext import ContextTypes

from utils.http import get_http_session
from utils.text import bold, code, italic, underline, link, mono

#weather
WEATHER_SPIN_FRAMES = ["🌤", "⛅", "🌥", "☁️"]

async def weather_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    if not context.args:
        return await msg.reply_text(
            "Example: <code>/weather jakarta</code>",
            parse_mode="HTML"
        )

    city = " ".join(context.args).strip()
    if not city:
        return await msg.reply_text(
            "Example: <code>/weather jakarta</code>",
            parse_mode="HTML"
        )

    status_msg = await msg.reply_text(
        f"🌤 Fetching weather for <b>{city.title()}</b>...",
        parse_mode="HTML"
    )

    session = await get_http_session()

    url = f"https://wttr.in/{city}?format=j1"
    headers = {
        "User-Agent": "Mozilla/5.0 (TelegramBot)"
    }

    try:
        async with session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status != 200:
                return await status_msg.edit_text(
                    "Failed to fetch weather data.\n"
                    "The weather server is busy, please try again later."
                )
            data = await resp.json()

    except asyncio.TimeoutError:
        return await status_msg.edit_text("Request timed out. Please try again later.")
    except Exception:
        return await status_msg.edit_text("Failed to reach the weather server.")

    try:
        current = data.get("current_condition", [{}])[0]

        weather_desc = current.get("weatherDesc", [{"value": "N/A"}])[0]["value"]
        temp_c = current.get("temp_C", "N/A")
        feels = current.get("FeelsLikeC", "N/A")
        humidity = current.get("humidity", "N/A")
        wind = f"{current.get('windspeedKmph','N/A')} km/h ({current.get('winddir16Point','N/A')})"
        cloud = current.get("cloudcover", "N/A")

        astronomy = data.get("weather", [{}])[0].get("astronomy", [{}])[0]
        sunrise = astronomy.get("sunrise", "N/A")
        sunset = astronomy.get("sunset", "N/A")

    except Exception:
        return await status_msg.edit_text("Error parsing weather data.")

    report = (
        f"🌤 <b>Weather — {city.title()}</b>\n\n"
        f"🔎 Condition : {weather_desc}\n"
        f"🌡 Temperature : {temp_c}°C (Feels like {feels}°C)\n"
        f"💧 Humidity : {humidity}%\n"
        f"💨 Wind : {wind}\n"
        f"☁️ Cloud cover : {cloud}%\n\n"
        f"🌅 Sunrise : {sunrise}\n"
        f"🌇 Sunset  : {sunset}\n\n"
        f"🕒 Updated : {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    await status_msg.edit_text(report, parse_mode="HTML")
    