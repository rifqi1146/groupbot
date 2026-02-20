import unittest
from unittest.mock import patch, MagicMock
import logging
import os
import sys

class TestStatsLogging(unittest.TestCase):
    def setUp(self):
        # Clean sys.modules to force reload of relevant modules
        # This ensures utils.config reads the new env vars we are about to set
        keys_to_remove = [k for k in sys.modules if k == 'handlers.stats' or k == 'utils.config' or k == 'utils.fonts']
        for k in keys_to_remove:
            del sys.modules[k]

        # Set env vars
        self.env_patcher = patch.dict(os.environ, {
            'BOT_TOKEN': '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ',
            'BOT_OWNER_ID': '123456,789012',
            'LOG_CHAT_ID': '-1001234567890',
            'SUPPORT_CH_ID': '-100111222333',
            'SUPPORT_CH_LINK': 'https://t.me/support',
        })
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def test_gather_stats_logs_exceptions(self):
        # Import inside the test so it sees the new env vars
        try:
            import handlers.stats
        except Exception as e:
            self.fail(f"Failed to import handlers.stats: {e}")

        # Patch psutil and shutil on the imported module using context managers
        with patch('handlers.stats.psutil') as mock_psutil, \
             patch('handlers.stats.shutil') as mock_shutil:

            # Configure mocks
            mock_psutil.cpu_percent.side_effect = Exception("Simulated CPU Error")
            mock_psutil.cpu_freq.side_effect = Exception("Simulated Freq Error")
            mock_psutil.virtual_memory.side_effect = Exception("Simulated RAM Error")
            mock_psutil.swap_memory.side_effect = Exception("Simulated Swap Error")
            mock_psutil.net_io_counters.side_effect = Exception("Simulated Net Error")

            mock_shutil.disk_usage.side_effect = Exception("Simulated Disk Error")

            # Run _gather_stats and capture logs
            # We use assertLogs to verify that errors are logged
            with self.assertLogs('handlers.stats', level='ERROR') as cm:
                stats = handlers.stats._gather_stats()

            # Verify logging content
            self.assertTrue(any("Simulated CPU Error" in log for log in cm.output), "CPU Error not logged")
            self.assertTrue(any("Simulated Disk Error" in log for log in cm.output), "Disk Error not logged")

            # Verify functionality (fallback values)
            self.assertEqual(stats["cpu"]["load"], 0.0)
            self.assertEqual(stats["disk"]["total"], 0)

if __name__ == '__main__':
    unittest.main()
