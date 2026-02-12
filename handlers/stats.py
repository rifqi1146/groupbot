import os
import time
import html
import shutil
import platform
import io

from telegram import Update
from telegram.ext import ContextTypes

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

    return "N/A"


def _safe_pct(x):
    try:
        v = float(x)
    except Exception:
        return 0.0
    if v < 0:
        return 0.0
    if v > 100:
        return 100.0
    return v


def _load_font(size: int, mono: bool = False):
    if not ImageFont:
        return None
    candidates = []
    if mono:
        candidates += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
        ]
    candidates += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
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


def _gather_stats():
    now = time.time()

    cpu_cores = os.cpu_count() or 0
    try:
        cpu_load = psutil.cpu_percent(interval=None) if psutil else 0.0
    except Exception:
        cpu_load = 0.0

    try:
        freq = psutil.cpu_freq() if psutil else None
        cpu_freq = f"{freq.current:.0f} MHz" if freq else "N/A"
    except Exception:
        cpu_freq = "N/A"

    ram_total = ram_used = ram_free = 0
    ram_pct = 0.0
    try:
        if psutil:
            vm = psutil.virtual_memory()
            ram_total = int(vm.total)
            ram_used = int(vm.used)
            ram_free = int(vm.available)
            ram_pct = float(vm.percent)
        else:
            mem = {}
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    k, v = line.split(":", 1)
                    mem[k.strip()] = int(v.strip().split()[0]) * 1024
            ram_total = int(mem.get("MemTotal", 0))
            ram_free = int(mem.get("MemAvailable", mem.get("MemFree", 0)))
            ram_used = int(max(0, ram_total - ram_free))
            ram_pct = (ram_used / ram_total * 100) if ram_total else 0.0
    except Exception:
        pass

    swap_total = swap_used = 0
    swap_pct = 0.0
    try:
        if psutil:
            sw = psutil.swap_memory()
            swap_total = int(sw.total)
            swap_used = int(sw.used)
            swap_pct = float(sw.percent)
    except Exception:
        pass

    disk_total = disk_used = disk_free = 0
    disk_pct = 0.0
    try:
        st = shutil.disk_usage("/")
        disk_total = int(st.total)
        disk_free = int(st.free)
        disk_used = int(st.total - st.free)
        disk_pct = (disk_used / disk_total * 100) if disk_total else 0.0
    except Exception:
        pass

    rx = tx = 0
    try:
        if psutil:
            net = psutil.net_io_counters()
            rx = int(net.bytes_recv)
            tx = int(net.bytes_sent)
    except Exception:
        pass

    os_name = _get_os_name()
    kernel = platform.release() or "N/A"
    pyver = platform.python_version() or "N/A"
    uptime = get_pretty_uptime()

    return {
        "ts": now,
        "cpu": {"cores": cpu_cores or "N/A", "load": float(cpu_load), "freq": cpu_freq},
        "ram": {"total": ram_total, "used": ram_used, "free": ram_free, "pct": float(ram_pct)},
        "swap": {"total": swap_total, "used": swap_used, "pct": float(swap_pct)},
        "disk": {"total": disk_total, "used": disk_used, "free": disk_free, "pct": float(disk_pct)},
        "net": {"rx": rx, "tx": tx},
        "sys": {"os": os_name, "kernel": kernel, "python": pyver, "uptime": uptime},
    }


def _draw_round_rect(draw, xy, r, fill=None, outline=None, width=1):
    x0, y0, x1, y1 = xy
    try:
        draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill, outline=outline, width=width)
        return
    except Exception:
        draw.rectangle([x0, y0, x1, y1], fill=fill, outline=outline, width=width)


def _bar(draw, x, y, w, h, pct, bg, fg, border, r=10):
    pct = _safe_pct(pct)
    _draw_round_rect(draw, (x, y, x + w, y + h), r, fill=bg, outline=border, width=1)
    fw = int(round(w * (pct / 100.0)))
    if fw > 0:
        _draw_round_rect(draw, (x, y, x + fw, y + h), r, fill=fg, outline=None, width=0)


def _render_dashboard(stats):
    if not Image or not ImageDraw or not ImageFont:
        return None

    W, H = 1280, 720

    bg0 = (12, 14, 18)
    bg1 = (18, 21, 28)
    card = (22, 26, 35)
    card2 = (26, 31, 42)
    border = (48, 56, 74)
    text = (232, 236, 243)
    muted = (160, 170, 190)

    bar_bg = (18, 22, 30)
    bar_fg = (90, 170, 255)
    bar_fg2 = (255, 140, 110)

    img = Image.new("RGB", (W, H), bg0)
    d = ImageDraw.Draw(img)

    for yy in range(H):
        t = yy / float(H - 1)
        r = int(bg0[0] * (1 - t) + bg1[0] * t)
        g = int(bg0[1] * (1 - t) + bg1[1] * t)
        b = int(bg0[2] * (1 - t) + bg1[2] * t)
        d.line([(0, yy), (W, yy)], fill=(r, g, b))

    f_title = _load_font(30, mono=False)
    f_h = _load_font(20, mono=False)
    f = _load_font(18, mono=False)
    f_mono = _load_font(18, mono=True)
    f_small = _load_font(14, mono=False)
    f_small_mono = _load_font(14, mono=True)

    pad = 28
    gap = 18

    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stats["ts"]))
    d.text((pad, pad - 2), "📈 System Stats", font=f_title, fill=text)
    d.text((pad, pad + 34), f"Updated: {ts}", font=f_small, fill=muted)

    x0 = pad
    y0 = pad + 78
    col_gap = gap
    col_w = (W - pad * 2 - col_gap) // 2
    left_x = x0
    right_x = x0 + col_w + col_gap

    top_h = 250
    bottom_h = H - y0 - top_h - gap

    cpu_card = (left_x, y0, left_x + col_w, y0 + top_h)
    sys_card = (right_x, y0, right_x + col_w, y0 + top_h)
    res_card = (left_x, y0 + top_h + gap, left_x + col_w, y0 + top_h + gap + bottom_h)
    net_card = (right_x, y0 + top_h + gap, right_x + col_w, y0 + top_h + gap + bottom_h)

    for rect, fillc in ((cpu_card, card), (sys_card, card), (res_card, card2), (net_card, card2)):
        _draw_round_rect(d, rect, 18, fill=fillc, outline=border, width=1)

    cx0, cy0, cx1, cy1 = cpu_card
    d.text((cx0 + 18, cy0 + 16), "⚙️ CPU", font=f_h, fill=text)

    cpu = stats["cpu"]
    cpu_load = _safe_pct(cpu["load"])
    d.text((cx0 + 18, cy0 + 56), f"Cores: {cpu['cores']}", font=f, fill=muted)
    d.text((cx0 + 18, cy0 + 80), f"Freq : {cpu['freq']}", font=f, fill=muted)

    bar_x = cx0 + 18
    bar_y = cy0 + 118
    bar_w = (cx1 - cx0) - 36
    bar_h = 22
    _bar(d, bar_x, bar_y, bar_w, bar_h, cpu_load, bar_bg, bar_fg, border, r=11)
    d.text((bar_x, bar_y + 30), f"Load: {cpu_load:.1f}%", font=f_mono, fill=text)

    try:
        if psutil:
            la = os.getloadavg()
            d.text((bar_x, bar_y + 56), f"LoadAvg: {la[0]:.2f} {la[1]:.2f} {la[2]:.2f}", font=f_small_mono, fill=muted)
    except Exception:
        pass

    sx0, sy0, sx1, sy1 = sys_card
    d.text((sx0 + 18, sy0 + 16), "🖥️ System", font=f_h, fill=text)

    sysi = stats["sys"]
    d.text((sx0 + 18, sy0 + 56), f"OS     : {sysi['os']}", font=f_small, fill=muted)
    d.text((sx0 + 18, sy0 + 78), f"Kernel : {sysi['kernel']}", font=f_small, fill=muted)
    d.text((sx0 + 18, sy0 + 100), f"Python : {sysi['python']}", font=f_small, fill=muted)
    d.text((sx0 + 18, sy0 + 122), f"Uptime : {sysi['uptime']}", font=f_small, fill=muted)

    rx = stats["net"]["rx"]
    tx = stats["net"]["tx"]
    d.text((sx0 + 18, sy0 + 160), "Quick Net", font=f, fill=text)
    d.text((sx0 + 18, sy0 + 184), f"RX: {humanize_bytes(rx)}", font=f_mono, fill=muted)
    d.text((sx0 + 18, sy0 + 206), f"TX: {humanize_bytes(tx)}", font=f_mono, fill=muted)

    rx0, ry0, rx1, ry1 = res_card
    d.text((rx0 + 18, ry0 + 16), "🧠 Memory + 💾 Disk", font=f_h, fill=text)

    ram = stats["ram"]
    ram_pct = _safe_pct(ram["pct"])
    d.text((rx0 + 18, ry0 + 58), "RAM", font=f, fill=text)
    d.text((rx0 + 90, ry0 + 58), f"{humanize_bytes(ram['used'])} / {humanize_bytes(ram['total'])}", font=f_mono, fill=muted)
    _bar(d, rx0 + 18, ry0 + 86, (rx1 - rx0) - 36, 22, ram_pct, bar_bg, bar_fg, border, r=11)
    d.text((rx0 + 18, ry0 + 114), f"{ram_pct:.1f}%", font=f_mono, fill=text)

    swap = stats["swap"]
    swap_total = int(swap["total"] or 0)
    swap_pct = _safe_pct(swap["pct"])
    d.text((rx0 + 18, ry0 + 148), "Swap", font=f, fill=text)
    if swap_total > 0:
        d.text((rx0 + 90, ry0 + 148), f"{humanize_bytes(swap['used'])} / {humanize_bytes(swap['total'])}", font=f_mono, fill=muted)
        _bar(d, rx0 + 18, ry0 + 176, (rx1 - rx0) - 36, 18, swap_pct, bar_bg, bar_fg2, border, r=9)
        d.text((rx0 + 18, ry0 + 198), f"{swap_pct:.1f}%", font=f_small_mono, fill=muted)
    else:
        d.text((rx0 + 90, ry0 + 148), "N/A", font=f_mono, fill=muted)

    disk = stats["disk"]
    disk_pct = _safe_pct(disk["pct"])
    d.text((rx0 + 18, ry0 + 232), "Disk (/)", font=f, fill=text)
    d.text((rx0 + 110, ry0 + 232), f"{humanize_bytes(disk['used'])} / {humanize_bytes(disk['total'])}", font=f_mono, fill=muted)
    _bar(d, rx0 + 18, ry0 + 260, (rx1 - rx0) - 36, 22, disk_pct, bar_bg, bar_fg, border, r=11)
    d.text((rx0 + 18, ry0 + 288), f"{disk_pct:.1f}% free {humanize_bytes(disk['free'])}", font=f_small_mono, fill=muted)

    nx0, ny0, nx1, ny1 = net_card
    d.text((nx0 + 18, ny0 + 16), "🌐 Network", font=f_h, fill=text)
    d.text((nx0 + 18, ny0 + 58), f"RX Total: {humanize_bytes(rx)}", font=f_mono, fill=muted)
    d.text((nx0 + 18, ny0 + 82), f"TX Total: {humanize_bytes(tx)}", font=f_mono, fill=muted)

    if psutil:
        try:
            pio = psutil.net_io_counters()
            rx0b = int(pio.bytes_recv)
            tx0b = int(pio.bytes_sent)
            t0 = time.time()
            time.sleep(0.25)
            pio2 = psutil.net_io_counters()
            rx1b = int(pio2.bytes_recv)
            tx1b = int(pio2.bytes_sent)
            dt = max(0.001, time.time() - t0)
            rxps = (rx1b - rx0b) / dt
            txps = (tx1b - tx0b) / dt
            d.text((nx0 + 18, ny0 + 120), "Speed (approx)", font=f, fill=text)
            d.text((nx0 + 18, ny0 + 144), f"RX/s: {humanize_bytes(int(rxps))}/s", font=f_mono, fill=muted)
            d.text((nx0 + 18, ny0 + 168), f"TX/s: {humanize_bytes(int(txps))}/s", font=f_mono, fill=muted)

            peak = max(rxps, txps, 1.0)
            rxp = min(100.0, (rxps / peak) * 100.0)
            txp = min(100.0, (txps / peak) * 100.0)

            d.text((nx0 + 18, ny0 + 206), "RX", font=f_small, fill=text)
            _bar(d, nx0 + 58, ny0 + 206, (nx1 - nx0) - 76, 16, rxp, bar_bg, bar_fg, border, r=8)

            d.text((nx0 + 18, ny0 + 234), "TX", font=f_small, fill=text)
            _bar(d, nx0 + 58, ny0 + 234, (nx1 - nx0) - 76, 16, txp, bar_bg, bar_fg2, border, r=8)
        except Exception:
            pass

    footer = f"PID: {os.getpid()}  •  Host: {platform.node() or 'N/A'}"
    d.text((pad, H - 24 - 2), footer, font=f_small, fill=(120, 130, 150))

    bio = io.BytesIO()
    bio.name = "stats.png"
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio


def _fallback_text(stats):
    cpu = stats["cpu"]
    ram = stats["ram"]
    swap = stats["swap"]
    disk = stats["disk"]
    net = stats["net"]
    sysi = stats["sys"]

    lines = []
    lines.append("📈 System Stats")
    lines.append("")
    lines.append(f"CPU: {cpu['load']:.1f}%  | Cores: {cpu['cores']} | Freq: {cpu['freq']}")
    lines.append(f"RAM: {humanize_bytes(ram['used'])}/{humanize_bytes(ram['total'])} ({ram['pct']:.1f}%)")
    if swap["total"]:
        lines.append(f"SWAP: {humanize_bytes(swap['used'])}/{humanize_bytes(swap['total'])} ({swap['pct']:.1f}%)")
    else:
        lines.append("SWAP: N/A")
    lines.append(f"DISK(/): {humanize_bytes(disk['used'])}/{humanize_bytes(disk['total'])} ({disk['pct']:.1f}%)")
    lines.append(f"NET: RX {humanize_bytes(net['rx'])} | TX {humanize_bytes(net['tx'])}")
    lines.append("")
    lines.append(f"OS: {sysi['os']}")
    lines.append(f"Kernel: {sysi['kernel']}")
    lines.append(f"Python: {sysi['python']}")
    lines.append(f"Uptime: {sysi['uptime']}")
    return "\n".join(lines)


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return

    stats = _gather_stats()
    bio = _render_dashboard(stats)

    if bio:
        return await msg.reply_photo(photo=bio)

    out = "<b>📈 System Stats</b>\n\n<pre>" + html.escape(_fallback_text(stats)) + "</pre>"
    return await msg.reply_text(out, parse_mode="HTML")