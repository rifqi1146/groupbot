from telegram import InlineKeyboardMarkup, InlineKeyboardButton


def dl_keyboard(dl_id: str):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Video", callback_data=f"dl:{dl_id}:video"),
                InlineKeyboardButton("MP3", callback_data=f"dl:{dl_id}:mp3"),
            ],
            [InlineKeyboardButton("Cancel", callback_data=f"dl:{dl_id}:cancel")],
        ]
    )


def yt_engine_keyboard(dl_id: str):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Use yt-dlp", callback_data=f"dlengine:{dl_id}:ytdlp"),
                InlineKeyboardButton("Use Sonzai API", callback_data=f"dlengine:{dl_id}:sonzai"),
            ],
            [InlineKeyboardButton("Cancel", callback_data=f"dl:{dl_id}:cancel")],
        ]
    )


from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def _fmt_size(num: int) -> str:
    try:
        num = int(num or 0)
    except Exception:
        num = 0
    if num <= 0:
        return ""
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return ""

def _res_button_label(item: dict) -> str:
    label = str(item.get("label") or "").strip()
    if not label:
        height = int(item.get("height") or 0)
        fps = int(item.get("fps") or 0)
        ext = str(item.get("ext") or "").strip()
        label = f"{height}p"
        if fps:
            label += str(fps)
        if ext:
            label += f"-{ext}"

    size = _fmt_size(item.get("total_size") or item.get("filesize") or 0)
    if size:
        label = f"{label} ({size})"

    return label[:40]

def res_keyboard(dl_id: str, res_list: list[dict], mode: str = "height"):
    rows = []
    row = []

    for idx, item in enumerate(res_list):
        if mode == "format":
            key = str(idx)
        else:
            key = str(int(item.get("height") or 0))

        if not key or key == "0":
            continue

        row.append(
            InlineKeyboardButton(
                _res_button_label(item),
                callback_data=f"dlres:{dl_id}:{key}",
            )
        )

        if len(row) == 2:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton("Cancel", callback_data=f"dl:{dl_id}:cancel")])
    return InlineKeyboardMarkup(rows)


def autodl_detect_keyboard(dl_id: str):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Download", callback_data=f"dlask:{dl_id}:go"),
                InlineKeyboardButton("Close", callback_data=f"dlask:{dl_id}:close"),
            ]
        ]
    )