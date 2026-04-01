import os
import time
import asyncio
import shutil
import platform
import logging
import socket

from .formatting import humanize_frequency
from .runtime_info import get_runtime_versions

logger = logging.getLogger(__name__)

try:
    import psutil
except Exception:
    psutil = None


def get_os_name():
    try:
        if os.path.exists("/etc/os-release"):
            with open("/etc/os-release") as f:
                os_info = {}
                for line in f:
                    if "=" in line:
                        key, value = line.strip().split("=", 1)
                        os_info[key] = value.strip('"')
            pretty = os_info.get("PRETTY_NAME")
            if pretty:
                return pretty
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


def gather_system_stats():
    now = time.time()

    cpu_cores = os.cpu_count() or 0
    try:
        cpu_load = psutil.cpu_percent(interval=1.0) if psutil else 0.0
    except Exception as e:
        logger.error(f"Failed to gather CPU load: {e}", exc_info=True)
        cpu_load = 0.0

    try:
        freq = psutil.cpu_freq() if psutil else None
        cpu_freq = humanize_frequency(freq.current) if freq else "N/A"
    except Exception as e:
        logger.error(f"Failed to gather CPU freq: {e}", exc_info=True)
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
                    key, value = line.split(":", 1)
                    mem[key.strip()] = int(value.strip().split()[0]) * 1024
            ram_total = int(mem.get("MemTotal", 0))
            ram_free = int(mem.get("MemAvailable", mem.get("MemFree", 0)))
            ram_used = int(max(0, ram_total - ram_free))
            ram_pct = (ram_used / ram_total * 100) if ram_total else 0.0
    except Exception as e:
        logger.error(f"Failed to gather RAM stats: {e}", exc_info=True)

    swap_total = swap_used = 0
    swap_pct = 0.0
    try:
        if psutil:
            sw = psutil.swap_memory()
            swap_total = int(sw.total)
            swap_used = int(sw.used)
            swap_pct = float(sw.percent)
    except Exception as e:
        logger.error(f"Failed to gather Swap stats: {e}", exc_info=True)

    disk_total = disk_used = disk_free = 0
    disk_pct = 0.0
    try:
        st = shutil.disk_usage("/")
        disk_total = int(st.total)
        disk_free = int(st.free)
        disk_used = int(st.total - st.free)
        disk_pct = (disk_used / disk_total * 100) if disk_total else 0.0
    except Exception as e:
        logger.error(f"Failed to gather Disk stats: {e}", exc_info=True)

    rx = tx = 0
    try:
        if psutil:
            net = psutil.net_io_counters()
            rx = int(net.bytes_recv)
            tx = int(net.bytes_sent)
    except Exception as e:
        logger.error(f"Failed to gather Network stats: {e}", exc_info=True)

    os_name = get_os_name()
    kernel = platform.release() or "N/A"
    pyver = platform.python_version() or "N/A"
    uptime = get_pretty_uptime()
    hostname = socket.gethostname() or platform.node() or "N/A"
    runtime = get_runtime_versions()

    return {
        "ts": now,
        "cpu": {"cores": cpu_cores or "N/A", "load": float(cpu_load), "freq": cpu_freq},
        "ram": {"total": ram_total, "used": ram_used, "free": ram_free, "pct": float(ram_pct)},
        "swap": {"total": swap_total, "used": swap_used, "pct": float(swap_pct)},
        "disk": {"total": disk_total, "used": disk_used, "free": disk_free, "pct": float(disk_pct)},
        "net": {"rx": rx, "tx": tx},
        "sys": {
            "hostname": hostname,
            "os": os_name,
            "kernel": kernel,
            "python": pyver,
            "uptime": uptime,
        },
        "runtime": runtime,
    }


async def measure_network_speed():
    if not psutil:
        return 0.0, 0.0
    try:
        first = psutil.net_io_counters()
        rx0 = int(first.bytes_recv)
        tx0 = int(first.bytes_sent)
        t0 = time.time()
        await asyncio.sleep(0.25)
        second = psutil.net_io_counters()
        rx1 = int(second.bytes_recv)
        tx1 = int(second.bytes_sent)
        dt = max(0.001, time.time() - t0)
        return (rx1 - rx0) / dt, (tx1 - tx0) / dt
    except Exception:
        return 0.0, 0.0