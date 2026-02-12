import os
import time
import html
import shutil
import platform
import io

from telegram import Update
from telegram.ext import ContextTypes

from handlers.dl import progress_bar

try:
    import psutil
except Exception:
    psutil = None

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None


def humanize_bytes(n: int) -> str:
    try:
        f = float(n)
    except Exception:
        return "N/A"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:.1f}{unit}"
        f /= 1024.0
    return f"{f:.1f}B"


def get_ram_info():
    try:
        if psutil:
            vm = psutil.virtual_memory()
            return {"total": vm.total, "used": vm.used, "free": vm.available, "percent": vm.percent}
        mem = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                k, v = line.split(":", 1)
                mem[k.strip()] = int(v.strip().split()[0]) * 1024
        total = mem.get("MemTotal", 0)
        free = mem.get("MemAvailable", mem.get("MemFree", 0))
        used = total - free
        percent = (used / total * 100) if total else 0.0
        return {"total": total, "used": used, "free": free, "percent": percent}
    except Exception:
        return None


def get_storage_info():
    try:
        mounts = {}
        paths = ["/data", "/storage", "/sdcard", "/"]
        seen = set()
        for p in paths:
            try:
                if os.path.exists(p):
                    st = shutil.disk_usage(p)
                    mounts[p] = {"total": st.total, "used": st.total - st.free, "free": st.free}
                    seen.add(p)
            except Exception:
                continue
        if "/" not in seen:
            st = shutil.disk_usage("/")
            mounts["/"] = {"total": st.total, "used": st.total - st.free, "free": st.free}
        return mounts
    except Exception:
        return None


def get_cpu_cores():
    try:
        cores = os.cpu_count()
        return cores or "N/A"
    except Exception:
        return "N/A"


def get_pretty_uptime():
    try:
        with open("/proc/uptime", "r") as f:
            up_seconds = float(f.readline().split()[0])
            secs = int(up_seconds)
            days, rem = divmod(secs, 86400)
            hours, rem = divmod(rem, 3600)
            minutes, seconds = divmod(rem, 60)
            parts = []
            if days:
                parts.append(f"{days}d")
            if hours:
                parts.append(f"{hours}h")
            if minutes:
                parts.append(f"{minutes}m")
            if not parts:
                parts.append(f"{seconds}s")
            return " ".join(parts)
    except Exception:
        pass

    try:
        if psutil:
            boot = psutil.boot_time()
            secs = int(time.time() - boot)
            days, rem = divmod(secs, 86400)
            hours, rem = divmod(rem, 3600)
            minutes, seconds = divmod(rem, 60)
            parts = []
            if days:
                parts.append(f"{days}d")
            if hours:
                parts.append(f"{hours}h")
            if minutes:
                parts.append(f"{minutes}m")
            if not parts:
                parts.append(f"{seconds}s")
            return " ".join(parts)
    except Exception:
        pass

    try:
        import subprocess
        out = subprocess.check_output(["uptime", "-p"], stderr=subprocess.DEVNULL, text=True).strip()
        if out.lower().startswith("up "):
            out = out[3:]
        parts = []
        for piece in out.split(","):
            piece = piece.strip()
            if piece.endswith("days") or piece.endswith("day"):
                n = piece.split()[0]
                parts.append(f"{n}d")
            elif piece.endswith("hours") or piece.endswith("hour"):
                n = piece.split()[0]
                parts.append(f"{n}h")
            elif piece.endswith("minutes") or piece.endswith("minute"):
                n = piece.split()[0]
                parts.append(f"{n}m")
        return " ".join(parts) if parts else out
    except Exception:
        return "N/A"


def _get_os_name():
    try:
        if os.path.exists("/etc/os-release"):
            with open("/etc/os-release") as f:
                os_info = {}
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        os_info[k] = v.strip('"')
            return f"{os_info.get('NAME', 'Linux')} {os_info.get('VERSION', '')}".strip()
        return (platform.system() + " " + platform.release()).strip()
    except Exception:
        return "Linux"


def _render_text_image(text: str):
    if not Image or not ImageDraw or not ImageFont:
        return None

    def _load_font(size: int):
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
        ]
        for p in candidates:
            try:
                if os.path.exists(p):
                    return ImageFont.truetype(p, size=size)
            except Exception:
                pass
        try:
            return ImageFont.load_default()
        except Exception:
            return None

    font = _load_font(18)
    title_font = _load_font(22) or font

    lines = text.splitlines()
    pad = 24
    line_gap = 6

    dummy = Image.new("RGB", (10, 10), (16, 18, 22))
    d = ImageDraw.Draw(dummy)

    max_w = 0
    line_h = 0
    for i, ln in enumerate(lines):
        f = title_font if i == 0 else font
        bbox = d.textbbox((0, 0), ln, font=f)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        if w > max_w:
            max_w = w
        if h > line_h:
            line_h = h

    width = max(720, max_w + pad * 2)
    height = pad * 2 + len(lines) * (line_h + line_gap) + 10

    img = Image.new("RGB", (width, height), (16, 18, 22))
    draw = ImageDraw.Draw(img)

    y = pad
    for i, ln in enumerate(lines):
        f = title_font if i == 0 else font
        color = (235, 238, 243)
        draw.text((pad, y), ln, font=f, fill=color)
        y += line_h + line_gap

    bio = io.BytesIO()
    bio.name = "stats.png"
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio


def _build_stats_text():
    ram = get_ram_info()
    storage = get_storage_info()
    cpu_cores = get_cpu_cores()
    uptime = get_pretty_uptime()

    os_name = _get_os_name()
    kernel = platform.release() or "N/A"
    python_ver = platform.python_version() or "N/A"

    try:
        cpu_load = psutil.cpu_percent(interval=None) if psutil else 0.0
    except Exception:
        cpu_load = 0.0

    try:
        freq = psutil.cpu_freq() if psutil else None
        cpu_freq = f"{freq.current:.0f} MHz" if freq else "N/A"
    except Exception:
        cpu_freq = "N/A"

    swap_text = []
    try:
        if psutil:
            swap = psutil.swap_memory()
            if getattr(swap, "total", 0) and swap.total > 0:
                swap_text = [
                    "",
                    "🧠 Swap",
                    f"  {humanize_bytes(swap.used)} / {humanize_bytes(swap.total)} ({swap.percent:.1f}%)",
                    f"  {progress_bar(swap.percent)}",
                ]
    except Exception:
        pass

    net_text = []
    try:
        if psutil:
            net = psutil.net_io_counters()
            net_text = [
                "",
                "🌐 Network",
                f"  ⬇️ RX: {humanize_bytes(net.bytes_recv)}",
                f"  ⬆️ TX: {humanize_bytes(net.bytes_sent)}",
            ]
    except Exception:
        pass

    lines = []
    lines.append("📈 System Stats")
    lines.append("")
    lines.append("⚙️ CPU")
    lines.append(f"  Cores : {cpu_cores}")
    lines.append(f"  Load  : {cpu_load:.1f}%")
    lines.append(f"  Freq  : {cpu_freq}")
    lines.append(f"  {progress_bar(cpu_load)}")
    lines.append("")

    if ram:
        lines.append("🧠 RAM")
        lines.append(f"  {humanize_bytes(ram['used'])} / {humanize_bytes(ram['total'])} ({ram['percent']:.1f}%)")
        lines.append(f"  {progress_bar(ram['percent'])}")
        lines.extend(swap_text)
    else:
        lines.append("🧠 RAM")
        lines.append("  Info unavailable")

    lines.append("")

    if storage and "/" in storage:
        v = storage["/"]
        pct = (v["used"] / v["total"] * 100) if v["total"] else 0.0
        lines.append("💾 Disk (/)")
        lines.append(f"  {humanize_bytes(v['used'])} / {humanize_bytes(v['total'])} ({pct:.1f}%)")
        lines.append(f"  {progress_bar(pct)}")
        lines.append("")

    lines.append("🖥️ System")
    lines.append(f"  OS     : {os_name}")
    lines.append(f"  Kernel : {kernel}")
    lines.append(f"  Python : {python_ver}")
    lines.append(f"  Uptime : {uptime}")

    lines.extend(net_text)

    return "\n".join(lines)


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return

    text = _build_stats_text()

    bio = _render_text_image(text)
    if bio:
        return await msg.reply_photo(photo=bio)

    out = "<b>📈 System Stats</b>\n\n" + html.escape(text)
    return await msg.reply_text(out, parse_mode="HTML")