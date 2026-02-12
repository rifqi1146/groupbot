import os
import json
import time
import asyncio
import subprocess
import math
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from telegram import Update
from telegram.ext import ContextTypes

from utils.config import OWNER_ID


IMG_W, IMG_H = 1920, 1080
S = 2


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


def _safe_get(d, path, default=None):
    cur = d
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur


def _human_ms(x):
    try:
        return f"{float(x):.1f} ms"
    except Exception:
        return "N/A"


def _human_mbps_from_bandwidth_bytes_per_s(bw):
    try:
        return float(bw) * 8.0 / 1e6
    except Exception:
        return 0.0


def _round_rect(draw, xy, r, fill, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=width)


def _lerp(a, b, t):
    return a + (b - a) * t


def _clamp(x, a, b):
    return a if x < a else b if x > b else x


def _mix(c1, c2, t):
    return (
        int(_lerp(c1[0], c2[0], t)),
        int(_lerp(c1[1], c2[1], t)),
        int(_lerp(c1[2], c2[2], t)),
        int(_lerp(c1[3], c2[3], t)) if len(c1) == 4 else 255
    )


def _draw_radial_glow(base, cx, cy, r, color=(0, 170, 255, 140)):
    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)

    steps = 10
    for i in range(steps):
        t = i / (steps - 1) if steps > 1 else 1
        rr = int(r * (0.55 + 0.85 * t))
        a = int(color[3] * (1.0 - t) * 0.35)
        col = (color[0], color[1], color[2], a)
        gd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=col, width=max(1, int(3 * S)))

    glow = glow.filter(ImageFilter.GaussianBlur(radius=int(18 * S)))
    base.alpha_composite(glow)


def _draw_arc_gradient(draw, bbox, start_deg, end_deg, width, c_start, c_end, steps=90):
    start_deg, end_deg = float(start_deg), float(end_deg)
    if end_deg < start_deg:
        start_deg, end_deg = end_deg, start_deg

    span = end_deg - start_deg
    steps = max(12, int(steps))
    for i in range(steps):
        t0 = i / steps
        t1 = (i + 1) / steps
        a0 = start_deg + span * t0
        a1 = start_deg + span * t1
        col = _mix(c_start, c_end, (t0 + t1) / 2)
        draw.arc(bbox, start=a0, end=a1, fill=col, width=width)


def _draw_ticks(draw, cx, cy, r_outer, r_inner, start_deg, end_deg, count, col, w):
    start_deg, end_deg = float(start_deg), float(end_deg)
    for i in range(count + 1):
        t = i / count if count else 0
        ang = math.radians(_lerp(start_deg, end_deg, t))
        x0 = cx + math.cos(ang) * r_inner
        y0 = cy + math.sin(ang) * r_inner
        x1 = cx + math.cos(ang) * r_outer
        y1 = cy + math.sin(ang) * r_outer
        draw.line((x0, y0, x1, y1), fill=col, width=w)


def _gauge_angle(value, max_val, start_deg=210, end_deg=-30):
    v = _clamp(float(value), 0.0, float(max_val))
    t = v / float(max_val) if max_val else 0.0
    return _lerp(start_deg, end_deg, t)


def _draw_needle(draw, cx, cy, ang_deg, r, col=(120, 220, 255, 255), w=6):
    ang = math.radians(ang_deg)
    x1 = cx + math.cos(ang) * r
    y1 = cy + math.sin(ang) * r
    draw.line((cx, cy, x1, y1), fill=col, width=w)
    draw.ellipse((cx - int(10*S), cy - int(10*S), cx + int(10*S), cy + int(10*S)), fill=(18, 22, 28, 255), outline=(140, 160, 190, 160), width=max(1, int(2*S)))


def _fmt_num(x, digits=1):
    try:
        return f"{float(x):.{digits}f}"
    except Exception:
        return "0.0"


def generate_image(data):
    W, H = IMG_W * S, IMG_H * S

    img = Image.new("RGBA", (W, H), (10, 12, 16, 255))
    d = ImageDraw.Draw(img)

    bg = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bg)
    bd.rectangle((0, 0, W, H), fill=(10, 12, 16, 255))
    bd.ellipse((-int(0.15*W), -int(0.2*H), int(0.55*W), int(0.75*H)), fill=(0, 170, 255, 32))
    bd.ellipse((int(0.55*W), -int(0.25*H), int(1.2*W), int(0.65*H)), fill=(130, 80, 255, 22))
    bd.ellipse((int(0.25*W), int(0.45*H), int(1.15*W), int(1.25*H)), fill=(0, 200, 140, 14))
    bg = bg.filter(ImageFilter.GaussianBlur(radius=int(70 * S)))
    img.alpha_composite(bg)

    title = "Speedtest"
    subtitle = "style dashboard"

    ping = float(_safe_get(data, ["ping", "latency"], 0.0) or 0.0)
    jitter = _safe_get(data, ["ping", "jitter"], None)
    packet_loss = _safe_get(data, ["packetLoss"], None)

    down = _human_mbps_from_bandwidth_bytes_per_s(_safe_get(data, ["download", "bandwidth"], 0) or 0)
    up = _human_mbps_from_bandwidth_bytes_per_s(_safe_get(data, ["upload", "bandwidth"], 0) or 0)

    isp = str(_safe_get(data, ["isp"], "N/A") or "N/A")
    srv_name = str(_safe_get(data, ["server", "name"], "") or "")
    srv_loc = str(_safe_get(data, ["server", "location"], "") or "")
    srv_cc = str(_safe_get(data, ["server", "country"], "") or "")
    srv_host = str(_safe_get(data, ["server", "host"], "") or "")
    srv = (srv_loc or srv_name or "N/A").strip()
    if srv_cc:
        srv = f"{srv} • {srv_cc}".strip(" •")

    ext_ip = str(_safe_get(data, ["interface", "externalIp"], "") or "")
    int_ip = str(_safe_get(data, ["interface", "internalIp"], "") or "")

    try:
        cpu = os.cpu_count() or 1
    except Exception:
        cpu = 1

    pad = int(52 * S)
    card_r = int(26 * S)

    c_card = (18, 22, 28, 210)
    c_card2 = (18, 22, 28, 180)
    c_line = (90, 110, 140, 80)
    c_text = (230, 238, 250, 255)
    c_muted = (160, 175, 198, 200)
    c_blue = (0, 170, 255, 255)
    c_blue2 = (120, 220, 255, 255)
    c_orange = (255, 120, 80, 255)

    FONT_TITLE = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(52 * S))
    FONT_SUB = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", int(22 * S))
    FONT_H = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(22 * S))
    FONT_V = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(70 * S))
    FONT_UNIT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", int(22 * S))
    FONT_K = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", int(18 * S))
    FONT_S = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", int(16 * S))

    d.text((pad, pad - int(6*S)), title, font=FONT_TITLE, fill=c_text)
    d.text((pad, pad + int(54*S)), subtitle, font=FONT_SUB, fill=c_muted)

    top_y = pad + int(110 * S)

    left_card = (pad, top_y, int(0.42*W), int(0.38*H))
    right_card = (int(0.46*W), top_y, W - pad, int(0.38*H))
    _round_rect(d, left_card, card_r, fill=c_card, outline=c_line, width=max(1, int(2*S)))
    _round_rect(d, right_card, card_r, fill=c_card, outline=c_line, width=max(1, int(2*S)))

    d.text((left_card[0] + int(26*S), left_card[1] + int(22*S)), "Latency", font=FONT_H, fill=c_text)

    d.text((left_card[0] + int(26*S), left_card[1] + int(70*S)), "PING", font=FONT_K, fill=c_muted)
    d.text((left_card[0] + int(26*S), left_card[1] + int(92*S)), _human_ms(ping), font=FONT_H, fill=c_blue2)

    d.text((left_card[0] + int(26*S), left_card[1] + int(130*S)), "JITTER", font=FONT_K, fill=c_muted)
    d.text((left_card[0] + int(26*S), left_card[1] + int(152*S)), _human_ms(jitter) if jitter is not None else "N/A", font=FONT_H, fill=c_text)

    d.text((left_card[0] + int(26*S), left_card[1] + int(190*S)), "PACKET LOSS", font=FONT_K, fill=c_muted)
    if packet_loss is None:
        pl = "N/A"
        pl_col = c_text
    else:
        try:
            plv = float(packet_loss)
            pl = f"{plv:.1f}%"
            pl_col = c_orange if plv > 0 else c_text
        except Exception:
            pl = "N/A"
            pl_col = c_text
    d.text((left_card[0] + int(26*S), left_card[1] + int(212*S)), pl, font=FONT_H, fill=pl_col)

    d.text((right_card[0] + int(26*S), right_card[1] + int(22*S)), "Server + Provider", font=FONT_H, fill=c_text)

    d.text((right_card[0] + int(26*S), right_card[1] + int(70*S)), "SERVER", font=FONT_K, fill=c_muted)
    d.text((right_card[0] + int(26*S), right_card[1] + int(92*S)), srv[:40], font=FONT_H, fill=c_text)

    d.text((right_card[0] + int(26*S), right_card[1] + int(130*S)), "HOST", font=FONT_K, fill=c_muted)
    d.text((right_card[0] + int(26*S), right_card[1] + int(152*S)), (srv_host or "N/A")[:44], font=FONT_S, fill=c_text)

    d.text((right_card[0] + int(26*S), right_card[1] + int(190*S)), "ISP", font=FONT_K, fill=c_muted)
    d.text((right_card[0] + int(26*S), right_card[1] + int(212*S)), isp[:44], font=FONT_H, fill=c_text)

    if ext_ip or int_ip:
        d.text((right_card[0] + int(26*S), right_card[1] + int(250*S)), "IP", font=FONT_K, fill=c_muted)
        ip_line = f"ext {ext_ip}" if ext_ip else ""
        ip2 = f"int {int_ip}" if int_ip else ""
        show = (ip_line + (" • " if ip_line and ip2 else "") + ip2).strip()
        d.text((right_card[0] + int(26*S), right_card[1] + int(272*S)), show[:60], font=FONT_S, fill=c_text)

    gauge_y0 = int(0.41 * H)
    gauge_h = H - gauge_y0 - pad
    bottom_card = (pad, gauge_y0, W - pad, H - pad)
    _round_rect(d, bottom_card, card_r, fill=c_card2, outline=c_line, width=max(1, int(2*S)))

    cx = int(W * 0.5)
    cy = int(gauge_y0 + gauge_h * 0.58)
    r = int(min(W, gauge_h) * 0.28)

    _draw_radial_glow(img, cx, cy, int(r * 1.15), color=(0, 170, 255, 150))

    bbox = (cx - r, cy - r, cx + r, cy + r)
    ring_w = int(22 * S)

    d.arc(bbox, start=210, end=-30, fill=(70, 85, 110, 90), width=ring_w)
    _draw_ticks(d, cx, cy, int(r * 1.02), int(r * 0.90), 210, -30, 16, (180, 200, 230, 70), max(1, int(3*S)))

    max_down = 500.0
    if down > 500:
        max_down = 1000.0
    if down > 1000:
        max_down = 2000.0

    ang_down = _gauge_angle(down, max_down, 210, -30)
    _draw_arc_gradient(
        d,
        bbox,
        210,
        ang_down,
        ring_w,
        (0, 170, 255, 220),
        (120, 220, 255, 255),
        steps=120
    )

    _draw_needle(d, cx, cy, ang_down, int(r * 0.88), col=(160, 235, 255, 230), w=max(2, int(6*S)))

    d.text((cx, cy - int(64*S)), "DOWNLOAD", font=FONT_H, fill=c_muted, anchor="mm")
    d.text((cx, cy + int(4*S)), _fmt_num(down, 1), font=FONT_V, fill=c_text, anchor="mm")
    d.text((cx, cy + int(72*S)), "Mbps", font=FONT_UNIT, fill=c_muted, anchor="mm")

    d.text((cx - int(r * 1.08), cy + int(r * 0.72)), "0", font=FONT_K, fill=(190, 205, 230, 90), anchor="mm")
    d.text((cx + int(r * 1.08), cy + int(r * 0.72)), f"{int(max_down)}", font=FONT_K, fill=(190, 205, 230, 90), anchor="mm")

    mini_r = int(r * 0.62)
    mini_cx = int(W * 0.78)
    mini_cy = int(gauge_y0 + gauge_h * 0.52)

    max_up = 200.0
    if up > 200:
        max_up = 500.0
    if up > 500:
        max_up = 1000.0

    mini_bbox = (mini_cx - mini_r, mini_cy - mini_r, mini_cx + mini_r, mini_cy + mini_r)
    d.arc(mini_bbox, start=210, end=-30, fill=(70, 85, 110, 90), width=int(18*S))
    _draw_ticks(d, mini_cx, mini_cy, int(mini_r * 1.02), int(mini_r * 0.88), 210, -30, 12, (180, 200, 230, 55), max(1, int(3*S)))

    ang_up = _gauge_angle(up, max_up, 210, -30)
    _draw_arc_gradient(
        d,
        mini_bbox,
        210,
        ang_up,
        int(18*S),
        (0, 200, 160, 210),
        (120, 255, 220, 255),
        steps=90
    )
    _draw_needle(d, mini_cx, mini_cy, ang_up, int(mini_r * 0.86), col=(150, 255, 225, 220), w=max(2, int(5*S)))

    d.text((mini_cx, mini_cy - int(38*S)), "UPLOAD", font=FONT_K, fill=c_muted, anchor="mm")
    d.text((mini_cx, mini_cy + int(6*S)), _fmt_num(up, 1), font=FONT_H, fill=c_text, anchor="mm")
    d.text((mini_cx, mini_cy + int(34*S)), "Mbps", font=FONT_S, fill=c_muted, anchor="mm")

    left_info_x = int(W * 0.22)
    d.text((left_info_x, int(gauge_y0 + int(56*S))), "RESULT", font=FONT_H, fill=c_text, anchor="mm")

    ping_str = _human_ms(ping)
    d.text((left_info_x, int(gauge_y0 + int(102*S))), "PING", font=FONT_K, fill=c_muted, anchor="mm")
    d.text((left_info_x, int(gauge_y0 + int(128*S))), ping_str, font=FONT_H, fill=c_text, anchor="mm")

    d.text((left_info_x, int(gauge_y0 + int(164*S))), "DOWNLOAD", font=FONT_K, fill=c_muted, anchor="mm")
    d.text((left_info_x, int(gauge_y0 + int(190*S))), f"{_fmt_num(down,1)} Mbps", font=FONT_H, fill=c_blue2, anchor="mm")

    d.text((left_info_x, int(gauge_y0 + int(226*S))), "UPLOAD", font=FONT_K, fill=c_muted, anchor="mm")
    d.text((left_info_x, int(gauge_y0 + int(252*S))), f"{_fmt_num(up,1)} Mbps", font=FONT_H, fill=(150, 255, 225, 230), anchor="mm")

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    d.text((W - pad, H - pad + int(4*S)), f"{ts}", font=FONT_S, fill=(160, 175, 198, 140), anchor="rd")

    img = img.resize((IMG_W, IMG_H), Image.Resampling.LANCZOS).convert("RGB")

    bio = BytesIO()
    bio.name = "speedtest.png"
    img.save(bio, "PNG", optimize=True)
    bio.seek(0)
    return bio


async def speedtest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user

    if not msg or not user:
        return

    if user.id not in OWNER_ID:
        return

    status = await msg.reply_text("⏳ Running Speedtest...")

    try:
        data = await asyncio.to_thread(run_speedtest)
        img = await asyncio.to_thread(generate_image, data)

        await msg.reply_photo(
            photo=img,
            reply_to_message_id=msg.message_id
        )
        await status.delete()

    except Exception as e:
        await status.edit_text(f"❌ Failed: {e}")
        

