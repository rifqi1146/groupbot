import unittest
from unittest.mock import MagicMock, patch
import sys
import asyncio
import os

# Mock dependencies
sys.modules["telegram"] = MagicMock()
sys.modules["telegram.ext"] = MagicMock()
sys.modules["psutil"] = MagicMock()
sys.modules["PIL"] = MagicMock()
sys.modules["PIL.Image"] = MagicMock()
sys.modules["PIL.ImageDraw"] = MagicMock()
sys.modules["PIL.ImageFont"] = MagicMock()

# Mock config before importing handlers
config_mock = MagicMock()
config_mock.FONT_DIR = None
sys.modules["utils.config"] = config_mock

# Add project root to path
sys.path.append(os.getcwd())

from handlers.stats import _gather_stats, _render_dashboard_sync, _measure_net_speed

class TestStats(unittest.IsolatedAsyncioTestCase):
    async def test_measure_net_speed(self):
        # Mock psutil behavior
        mock_psutil = sys.modules["psutil"]
        mock_psutil.net_io_counters.side_effect = [
            MagicMock(bytes_recv=1000, bytes_sent=1000),
            MagicMock(bytes_recv=2000, bytes_sent=2000)
        ]

        rx_speed, tx_speed = await _measure_net_speed()

        # Expect roughly (2000-1000)/0.25 = 4000 bytes/s
        # Allow some margin due to time.time() delta
        self.assertGreater(rx_speed, 3000)
        self.assertLess(rx_speed, 5000)
        self.assertGreater(tx_speed, 3000)
        self.assertLess(tx_speed, 5000)

    def test_gather_stats(self):
        # Mock psutil behavior for gather_stats
        mock_psutil = sys.modules["psutil"]
        mock_psutil.cpu_percent.return_value = 10.0
        mock_psutil.cpu_freq.return_value = MagicMock(current=2000.0)
        mock_psutil.virtual_memory.return_value = MagicMock(total=100, used=50, available=50, percent=50.0)
        mock_psutil.swap_memory.return_value = MagicMock(total=0, used=0, percent=0.0)
        mock_psutil.net_io_counters.return_value = MagicMock(bytes_recv=100, bytes_sent=100)

        stats = _gather_stats()

        self.assertIn("cpu", stats)
        self.assertEqual(stats["cpu"]["load"], 10.0)
        self.assertEqual(stats["ram"]["pct"], 50.0)

    def test_render_dashboard_sync(self):
        # Mock stats
        stats = {
            "ts": 1234567890,
            "cpu": {"cores": 4, "load": 10.0, "freq": "2.0GHz"},
            "ram": {"total": 1000, "used": 500, "free": 500, "pct": 50.0},
            "swap": {"total": 0, "used": 0, "pct": 0.0},
            "disk": {"total": 1000, "used": 500, "free": 500, "pct": 50.0},
            "net": {"rx": 1000, "tx": 1000},
            "sys": {"os": "Linux", "kernel": "5.10", "python": "3.9", "uptime": "1d"},
        }

        # Mock PIL image creation
        mock_image = sys.modules["PIL.Image"]
        mock_image.new.return_value = MagicMock()

        bio = _render_dashboard_sync(stats, net_speed=(100.0, 100.0))

        # Should return a BytesIO object (mocked save call)
        # Since we mocked PIL, _render_dashboard_sync might return bio but empty because save is mocked.
        # Check if it returns a BytesIO object (which has a 'name' attribute set in the code)
        self.assertIsNotNone(bio)
        self.assertEqual(bio.name, "stats.png")

if __name__ == "__main__":
    unittest.main()
