import os
import time
import html
import shutil
import platform
from telegram import Update
from telegram.ext import ContextTypes

from handlers.dl import progress_bar
from utils.text import bold, code, italic, underline, link, mono

#stats
try:
    import psutil
except Exception:
    psutil = None

def humanize_bytes(n: int) -> str:
    try:
        f = float(n)
    except Exception:
        return "N/A"
    for unit in ("B","KB","MB","GB","TB"):
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

def get_kernel_version():
    try:
        return platform.release() or "N/A"
    except Exception:
        return "N/A"

def get_os_name():
    try:
        name = platform.system() or "Linux"
        rel = platform.version() or platform.release() or ""
        return f"{name} {rel}".strip()
    except Exception:
        return "N/A"

def get_cpu_cores():
    try:
        cores = os.cpu_count()
        return cores or "N/A"
    except Exception:
        return "N/A"

def get_python_version():
    try:
        return platform.python_version()
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
                n = piece.split()[0]; parts.append(f"{n}d")
            elif piece.endswith("hours") or piece.endswith("hour"):
                n = piece.split()[0]; parts.append(f"{n}h")
            elif piece.endswith("minutes") or piece.endswith("minute"):
                n = piece.split()[0]; parts.append(f"{n}m")
        return " ".join(parts) if parts else out
    except Exception:
        return "N/A"

#cmd stats
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ram = get_ram_info()
    storage = get_storage_info()
    cpu_cores = get_cpu_cores()
    uptime = get_pretty_uptime()
    
    try:
        if os.path.exists("/etc/os-release"):
            with open("/etc/os-release") as f:
                os_info = {}
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        os_info[k] = v.strip('"')
            os_name = f"{os_info.get('NAME', 'Linux')} {os_info.get('VERSION', '')}".strip()
        else:
            os_name = platform.system() + " " + platform.release()
    except Exception:
        os_name = "Linux"

    kernel = platform.release()
    python_ver = platform.python_version()

    try:
        cpu_load = psutil.cpu_percent(interval=None)
    except Exception:
        cpu_load = 0.0

    try:
        freq = psutil.cpu_freq()
        cpu_freq = f"{freq.current:.0f} MHz" if freq else "N/A"
    except Exception:
        cpu_freq = "N/A"

    swap_line = ""
    try:
        swap = psutil.swap_memory()
        swap_line = (
            f"\n<b>🧠 Swap</b>\n"
            f"  {humanize_bytes(swap.used)} / {humanize_bytes(swap.total)} ({swap.percent:.1f}%)\n"
            f"  {progress_bar(swap.percent)}"
        ) if swap.total > 0 else ""
    except Exception:
        pass

    net_line = ""
    try:
        net = psutil.net_io_counters()
        net_line = (
            "\n<b>🌐 Network</b>\n"
            f"  ⬇️ RX: {humanize_bytes(net.bytes_recv)}\n"
            f"  ⬆️ TX: {humanize_bytes(net.bytes_sent)}"
        )
    except Exception:
        pass

    lines = []
    lines.append("<b>📈 System Stats</b>")
    lines.append("")

    lines.append("<b>⚙️ CPU</b>")
    lines.append(f"  Cores : {cpu_cores}")
    lines.append(f"  Load  : {cpu_load:.1f}%")
    lines.append(f"  Freq  : {cpu_freq}")
    lines.append(f"  {progress_bar(cpu_load)}")
    lines.append("")

    if ram:
        lines.append("<b>🧠 RAM</b>")
        lines.append(f"  {humanize_bytes(ram['used'])} / {humanize_bytes(ram['total'])} ({ram['percent']:.1f}%)")
        lines.append(f"  {progress_bar(ram['percent'])}")
        if swap_line:
            lines.append(swap_line)
    else:
        lines.append("<b>🧠 RAM</b> Info unavailable")

    lines.append("")

    if storage and "/" in storage:
        v = storage["/"]
        pct = (v["used"] / v["total"] * 100) if v["total"] else 0.0
        lines.append("<b>💾 Disk (/)</b>")
        lines.append(f"  {humanize_bytes(v['used'])} / {humanize_bytes(v['total'])} ({pct:.1f}%)")
        lines.append(f"  {progress_bar(pct)}")

    lines.append("")

    lines.append("<b>🖥️ System</b>")
    lines.append(f"  OS     : {html.escape(os_name)}")
    lines.append(f"  Kernel : {html.escape(kernel)}")
    lines.append(f"  Python : {html.escape(python_ver)}")
    lines.append(f"  Uptime : {html.escape(uptime)}")

    if net_line:
        lines.append(net_line)

    out = "\n".join(lines)

    await update.message.reply_text(out, parse_mode="HTML")

