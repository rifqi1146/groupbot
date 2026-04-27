import io
import functools

from utils.fonts import get_font
from .formatting import humanize_bytes, shorten_text, clamp_percent

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None


@functools.lru_cache(maxsize=32)
def load_font(size: int, mono: bool = False):
    if not ImageFont:
        return None
    if mono:
        return get_font(["DejaVuSansMono.ttf", "LiberationMono-Regular.ttf", "FreeMono.ttf"], size)
    return get_font(["DejaVuSans.ttf", "LiberationSans-Regular.ttf"], size)


def draw_rounded_rect(draw, xy, radius, fill=None, outline=None, width=1):
    x0, y0, x1, y1 = xy
    try:
        draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill, outline=outline, width=width)
        return
    except Exception:
        draw.rectangle([x0, y0, x1, y1], fill=fill, outline=outline, width=width)


def draw_progress_bar(draw, x, y, w, h, pct, bg, fg, border, radius=10):
    pct = clamp_percent(pct)
    draw_rounded_rect(draw, (x, y, x + w, y + h), radius, fill=bg, outline=border, width=1)
    fill_width = int(round(w * (pct / 100.0)))
    if fill_width > 0:
        draw_rounded_rect(draw, (x, y, x + fill_width, y + h), radius, fill=fg, outline=None, width=0)


def render_dashboard(stats, net_speed=(0.0, 0.0)):
    if not Image or not ImageDraw or not ImageFont:
        return None

    width, height = 1920, 1080
    scale = 1.5

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

    img = Image.new("RGB", (width, height), bg0)
    draw = ImageDraw.Draw(img)

    for y in range(height):
        t = y / float(height - 1)
        r = int(bg0[0] * (1 - t) + bg1[0] * t)
        g = int(bg0[1] * (1 - t) + bg1[1] * t)
        b = int(bg0[2] * (1 - t) + bg1[2] * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    font_title = load_font(int(30 * scale), mono=False)
    font_heading = load_font(int(20 * scale), mono=False)
    font_body = load_font(int(18 * scale), mono=False)
    font_mono = load_font(int(18 * scale), mono=True)
    font_small = load_font(int(14 * scale), mono=False)
    font_small_mono = load_font(int(14 * scale), mono=True)
    font_tiny = load_font(int(12 * scale), mono=False)

    pad = int(28 * scale)
    gap = int(18 * scale)

    draw.text((pad, int(pad - 2 * scale)), "System Stats", font=font_title, fill=text)

    x0 = pad
    y0 = pad + int(78 * scale)
    col_gap = gap
    col_w = (width - pad * 2 - col_gap) // 2
    left_x = x0
    right_x = x0 + col_w + col_gap

    top_h = int(250 * scale)
    bottom_h = height - y0 - top_h - gap

    cpu_card = (left_x, y0, left_x + col_w, y0 + top_h)
    sys_card = (right_x, y0, right_x + col_w, y0 + top_h)
    res_card = (left_x, y0 + top_h + gap, left_x + col_w, y0 + top_h + gap + bottom_h)
    net_card = (right_x, y0 + top_h + gap, right_x + col_w, y0 + top_h + gap + bottom_h)

    for rect, fillc in ((cpu_card, card), (sys_card, card), (res_card, card2), (net_card, card2)):
        draw_rounded_rect(draw, rect, int(18 * scale), fill=fillc, outline=border, width=1)

    cx0, cy0, cx1, cy1 = cpu_card
    draw.text((cx0 + int(18 * scale), cy0 + int(16 * scale)), "CPU", font=font_heading, fill=text)

    cpu = stats["cpu"]
    cpu_load = clamp_percent(cpu["load"])
    draw.text((cx0 + int(18 * scale), cy0 + int(56 * scale)), f"Cores: {cpu['cores']}", font=font_body, fill=muted)
    draw.text((cx0 + int(18 * scale), cy0 + int(80 * scale)), f"Freq : {cpu['freq']}", font=font_body, fill=muted)

    bar_x = cx0 + int(18 * scale)
    bar_y = cy0 + int(118 * scale)
    bar_w = (cx1 - cx0) - int(36 * scale)
    bar_h = int(22 * scale)
    draw_progress_bar(draw, bar_x, bar_y, bar_w, bar_h, cpu_load, bar_bg, bar_fg, border, radius=int(11 * scale))
    draw.text((bar_x, bar_y + int(30 * scale)), f"Load: {cpu_load:.1f}%", font=font_mono, fill=text)

    sx0, sy0, sx1, sy1 = sys_card
    draw.text((sx0 + int(18 * scale), sy0 + int(16 * scale)), "System + Runtime", font=font_heading, fill=text)

    sysi = stats["sys"]
    runtime = stats["runtime"]

    sys_lines = [
        f"Host    : {shorten_text(sysi['hostname'], 56)}",
        f"OS      : {shorten_text(sysi['os'], 56)}",
        f"Kernel  : {sysi['kernel']}",
        f"Python  : {sysi['python']}",
        f"Uptime  : {sysi['uptime']}",
        f"Node    : {runtime['node']}",
        f"Deno    : {runtime['deno']}",
        f"yt-dlp  : {runtime['ytdlp']}",
        f"aria2c  : {runtime['aria2c']}",
        f"python-telegram-bot     : {runtime['ptb']}",
        f"HTTP    : aiohttp {runtime['aiohttp']}",
        f"Core    : Pillow {runtime['pillow']} • psutil {runtime['psutil']} • aiofiles {runtime['aiofiles']}",
    ]

    sys_y = sy0 + int(52 * scale)
    sys_step = int(16 * scale)
    for line in sys_lines:
        draw.text((sx0 + int(18 * scale), sys_y), line, font=font_tiny, fill=muted)
        sys_y += sys_step

    rx0, ry0, rx1, ry1 = res_card
    draw.text((rx0 + int(18 * scale), ry0 + int(16 * scale)), "Memory + Disk", font=font_heading, fill=text)

    ram = stats["ram"]
    ram_pct = clamp_percent(ram["pct"])
    draw.text((rx0 + int(18 * scale), ry0 + int(58 * scale)), "RAM", font=font_body, fill=text)
    draw.text((rx0 + int(90 * scale), ry0 + int(58 * scale)), f"{humanize_bytes(ram['used'])} / {humanize_bytes(ram['total'])}", font=font_mono, fill=muted)
    draw_progress_bar(draw, rx0 + int(18 * scale), ry0 + int(86 * scale), (rx1 - rx0) - int(36 * scale), int(22 * scale), ram_pct, bar_bg, bar_fg, border, radius=int(11 * scale))
    draw.text((rx0 + int(18 * scale), ry0 + int(114 * scale)), f"{ram_pct:.1f}%", font=font_mono, fill=text)

    swap = stats["swap"]
    swap_total = int(swap["total"] or 0)
    swap_pct = clamp_percent(swap["pct"])
    draw.text((rx0 + int(18 * scale), ry0 + int(148 * scale)), "Swap", font=font_body, fill=text)
    if swap_total > 0:
        draw.text((rx0 + int(90 * scale), ry0 + int(148 * scale)), f"{humanize_bytes(swap['used'])} / {humanize_bytes(swap['total'])}", font=font_mono, fill=muted)
        draw_progress_bar(draw, rx0 + int(18 * scale), ry0 + int(176 * scale), (rx1 - rx0) - int(36 * scale), int(18 * scale), swap_pct, bar_bg, bar_fg2, border, radius=int(9 * scale))
        draw.text((rx0 + int(18 * scale), ry0 + int(198 * scale)), f"{swap_pct:.1f}%", font=font_small_mono, fill=muted)
    else:
        draw.text((rx0 + int(90 * scale), ry0 + int(148 * scale)), "N/A", font=font_mono, fill=muted)

    disk = stats["disk"]
    disk_pct = clamp_percent(disk["pct"])
    draw.text((rx0 + int(18 * scale), ry0 + int(232 * scale)), "Disk (/)", font=font_body, fill=text)
    draw.text((rx0 + int(110 * scale), ry0 + int(232 * scale)), f"{humanize_bytes(disk['used'])} / {humanize_bytes(disk['total'])}", font=font_mono, fill=muted)
    draw_progress_bar(draw, rx0 + int(18 * scale), ry0 + int(260 * scale), (rx1 - rx0) - int(36 * scale), int(22 * scale), disk_pct, bar_bg, bar_fg, border, radius=int(11 * scale))
    draw.text((rx0 + int(18 * scale), ry0 + int(288 * scale)), f"Used {disk_pct:.1f}% • Free {humanize_bytes(disk['free'])}", font=font_small_mono, fill=muted)

    nx0, ny0, nx1, ny1 = net_card
    draw.text((nx0 + int(18 * scale), ny0 + int(16 * scale)), "Network", font=font_heading, fill=text)

    net = stats["net"]
    rx = net["rx"]
    tx = net["tx"]

    draw.text((nx0 + int(18 * scale), ny0 + int(58 * scale)), f"RX Total: {humanize_bytes(rx)}", font=font_mono, fill=muted)
    draw.text((nx0 + int(18 * scale), ny0 + int(82 * scale)), f"TX Total: {humanize_bytes(tx)}", font=font_mono, fill=muted)

    try:
        if isinstance(net_speed, dict):
            rxps = float(net_speed.get("rxps") or 0)
            txps = float(net_speed.get("txps") or 0)
            max_bps = float(net_speed.get("max_bps") or (10 * 1024 * 1024))
        else:
            rxps, txps = net_speed
            max_bps = 10 * 1024 * 1024

        rxp = min(100.0, max(0.0, (rxps / max_bps) * 100.0))
        txp = min(100.0, max(0.0, (txps / max_bps) * 100.0))

        draw.text((nx0 + int(18 * scale), ny0 + int(124 * scale)), "Speed", font=font_body, fill=text)
        draw.text((nx0 + int(18 * scale), ny0 + int(148 * scale)), f"RX/s: {humanize_bytes(int(rxps))}/s", font=font_mono, fill=muted)
        draw.text((nx0 + int(18 * scale), ny0 + int(172 * scale)), f"TX/s: {humanize_bytes(int(txps))}/s", font=font_mono, fill=muted)

        draw.text((nx0 + int(18 * scale), ny0 + int(214 * scale)), "RX", font=font_small, fill=text)
        draw_progress_bar(draw, nx0 + int(58 * scale), ny0 + int(214 * scale), (nx1 - nx0) - int(76 * scale), int(16 * scale), rxp, bar_bg, bar_fg, border, radius=int(8 * scale))

        draw.text((nx0 + int(18 * scale), ny0 + int(244 * scale)), "TX", font=font_small, fill=text)
        draw_progress_bar(draw, nx0 + int(58 * scale), ny0 + int(244 * scale), (nx1 - nx0) - int(76 * scale), int(16 * scale), txp, bar_bg, bar_fg2, border, radius=int(8 * scale))
    except Exception:
        pass

    bio = io.BytesIO()
    bio.name = "stats.png"
    img.save(bio, format="PNG", compress_level=3)
    bio.seek(0)
    return bio