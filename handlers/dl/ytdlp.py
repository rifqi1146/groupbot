import os
import uuid
import asyncio
import shutil
from .constants import COOKIES_PATH, TMP_DIR
from .utils import progress_bar

async def ytdlp_download(
    url,
    fmt_key,
    bot,
    chat_id,
    status_msg_id,
    format_id: str | None = None,
    has_audio: bool = False,
):
    YT_DLP = shutil.which("yt-dlp")
    if not YT_DLP:
        raise RuntimeError("yt-dlp not found in PATH")

    out_tpl = f"{TMP_DIR}/%(title)s.%(ext)s"

    async def run(cmd):
        print("\n[YTDLP CMD]")
        print(" ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )

        last_edit = 0
        last_pct = -1

        while True:
            line = await proc.stdout.readline()
            if not line:
                break

            raw = line.decode(errors="ignore").strip()
            print("[YTDLP STDOUT]", raw)

            if "|" not in raw:
                continue

            head = raw.split("|", 1)[0].replace("%", "")
            if not head.replace(".", "", 1).isdigit():
                continue

            pct = float(head)
            if pct <= last_pct:
                continue
            last_pct = pct

            now = __import__("time").time()
            if now - last_edit >= 3:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=status_msg_id,
                        text=(
                            "🚀 <b>yt-dlp download...</b>\n\n"
                            f"<code>{progress_bar(pct)} {pct:.1f}%</code>"
                        ),
                        parse_mode="HTML",
                    )
                except Exception as e:
                    print("[TG EDIT ERROR]", e)

                last_edit = now

        stdout, stderr = await proc.communicate()

        if stdout:
            print("\n[YTDLP STDOUT REMAIN]")
            print(stdout.decode(errors="ignore"))

        if stderr:
            print("\n[YTDLP STDERR]")
            print(stderr.decode(errors="ignore"))

        print("[YTDLP EXIT CODE]", proc.returncode)
        return proc.returncode

    if fmt_key == "mp3":
        code = await run(
            [
                YT_DLP,
                "--cookies", COOKIES_PATH,
                "--js-runtimes", "deno:/root/.deno/bin/deno",
                "--no-playlist",
                "-f", "bestaudio/best",
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", "0",
                "--newline",
                "--progress-template", "%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
                "-o", out_tpl,
                url,
            ]
        )
        if code != 0:
            return None
    else:
        if format_id:
            if has_audio:
                fmt = format_id
            else:
                fmt = f"{format_id}+bestaudio/best"
        else:
            fmt = "bestvideo*+bestaudio/best"

        code = await run(
            [
                YT_DLP,
                "--cookies", COOKIES_PATH,
                "--js-runtimes", "deno:/root/.deno/bin/deno",
                "--no-playlist",
                "-f", fmt,
                "--merge-output-format", "mp4",
                "--newline",
                "--progress-template", "%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
                "-o", out_tpl,
                url,
            ]
        )

        if code != 0:
            print("[YTDLP] video failed → trying bestimage")
            code = await run(
                [
                    YT_DLP,
                    "--cookies", COOKIES_PATH,
                    "--no-playlist",
                    "-f", "bestimage",
                    "-o", out_tpl,
                    url,
                ]
            )
            if code != 0:
                return None

    def media_priority(p):
        p = p.lower()
        if p.endswith(".mp4"):
            return 0
        if p.endswith(".mp3"):
            return 1
        if p.endswith((".jpg", ".jpeg", ".png", ".webp")):
            return 2
        return 9

    files = sorted(
        (
            os.path.join(TMP_DIR, f)
            for f in os.listdir(TMP_DIR)
            if f.lower().endswith((".mp4", ".mp3", ".jpg", ".jpeg", ".png", ".webp"))
        ),
        key=lambda p: (media_priority(p), -os.path.getmtime(p)),
    )

    print("[YTDLP OUTPUT FILES]", files)
    return files[0] if files else None