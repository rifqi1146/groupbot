import os
import sys
import unittest
import time
from unittest.mock import MagicMock, patch

# Set dummy env vars to satisfy utils.config
os.environ["BOT_TOKEN"] = "123:ABC"
os.environ["BOT_OWNER_ID"] = "123"
os.environ["LOG_CHAT_ID"] = "123"

# Mock telegram
sys.modules["telegram"] = MagicMock()
sys.modules["telegram.ext"] = MagicMock()

# Mock dotenv
sys.modules["dotenv"] = MagicMock()

# Mock PIL
sys.modules["PIL"] = MagicMock()
sys.modules["PIL.Image"] = MagicMock()
sys.modules["PIL.ImageDraw"] = MagicMock()
sys.modules["PIL.ImageFont"] = MagicMock()

# Mock psutil (default to installed for test setup)
psutil_mock = MagicMock()
sys.modules["psutil"] = psutil_mock

# Import the module under test
from handlers import stats

class TestStats(unittest.TestCase):
    def setUp(self):
        psutil_mock.reset_mock()
        # Ensure stats.psutil points to our mock by default
        stats.psutil = psutil_mock

    def test_gather_stats_structure(self):
        # Setup psutil mock return values
        psutil_mock.cpu_percent.return_value = 15.0

        freq_mock = MagicMock()
        freq_mock.current = 2400
        psutil_mock.cpu_freq.return_value = freq_mock

        vm_mock = MagicMock()
        vm_mock.total = 16000000000
        vm_mock.used = 8000000000
        vm_mock.available = 8000000000
        vm_mock.percent = 50.0
        psutil_mock.virtual_memory.return_value = vm_mock

        sw_mock = MagicMock()
        sw_mock.total = 4000000000
        sw_mock.used = 1000000000
        sw_mock.percent = 25.0
        psutil_mock.swap_memory.return_value = sw_mock

        net_mock = MagicMock()
        net_mock.bytes_recv = 1000
        net_mock.bytes_sent = 2000
        psutil_mock.net_io_counters.return_value = net_mock

        res = stats._gather_stats()

        self.assertIsInstance(res, dict)
        self.assertIn("ts", res)
        self.assertIn("cpu", res)
        self.assertEqual(res["cpu"]["load"], 15.0)
        self.assertEqual(res["cpu"]["freq"], "2400 MHz")

        self.assertIn("ram", res)
        self.assertEqual(res["ram"]["total"], 16000000000)
        self.assertEqual(res["ram"]["pct"], 50.0)

        self.assertIn("swap", res)
        self.assertEqual(res["swap"]["total"], 4000000000)
        self.assertEqual(res["swap"]["pct"], 25.0)

        self.assertIn("net", res)
        self.assertEqual(res["net"]["rx"], 1000)
        self.assertEqual(res["net"]["tx"], 2000)

        self.assertIn("sys", res)
        self.assertIn("disk", res)

    def test_gather_stats_no_psutil(self):
        # Simulate psutil missing
        stats.psutil = None

        # We need to mock open for /proc/meminfo fallback or accept exceptions
        # The current code has try-except blocks which will result in 0/N/A if file reading fails

        with patch("builtins.open", unittest.mock.mock_open(read_data="MemTotal: 1000 kB\nMemFree: 500 kB\n")):
             res = stats._gather_stats()

        self.assertEqual(res["cpu"]["load"], 0.0)
        # ram might be parsed from mock_open data if implemented correctly
        # The code reads /proc/meminfo. "MemTotal: 1000 kB" -> 1000*1024
        # "MemFree: 500 kB" -> 500*1024. Available approx Free.
        # used = total - free = 500*1024.

        # Let's verify RAM if possible, but the code does:
        # mem[k.strip()] = int(v.strip().split()[0]) * 1024
        # ram_total = mem.get("MemTotal")
        # ram_free = mem.get("MemAvailable", mem.get("MemFree"))

        # So yes, it should work with mock_open
        self.assertEqual(res["ram"]["total"], 1000 * 1024)
        self.assertEqual(res["ram"]["free"], 500 * 1024)
        self.assertEqual(res["ram"]["used"], 500 * 1024)
        self.assertEqual(res["ram"]["pct"], 50.0)

if __name__ == "__main__":
    unittest.main()
