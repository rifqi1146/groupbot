
import unittest
from unittest.mock import patch, MagicMock
import asyncio
import sys

# Mock dependencies to avoid import errors when running in isolation
# We need to mock these BEFORE importing handlers.caca
sys.modules['telegram'] = MagicMock()
sys.modules['telegram.ext'] = MagicMock()
sys.modules['aiohttp'] = MagicMock()
sys.modules['bs4'] = MagicMock()
sys.modules['handlers.gsearch'] = MagicMock()
sys.modules['utils.ai_utils'] = MagicMock()
sys.modules['utils.config'] = MagicMock()
sys.modules['utils.http'] = MagicMock()
sys.modules['utils.caca_db'] = MagicMock()
sys.modules['utils.caca_memory'] = MagicMock()

# Now import the module under test
from handlers import caca

class TestCacaInit(unittest.TestCase):
    @patch('asyncio.get_event_loop')
    def test_init_background_propagates_exception(self, mock_get_loop):
        """
        Verify that init_background propagates exceptions instead of swallowing them.
        This ensures that startup errors are logged by the caller (e.g. startup.py).
        """
        # Setup mock to raise exception
        mock_get_loop.side_effect = Exception("Boom")

        # We expect init_background to propagate the exception
        with self.assertRaises(Exception) as context:
            caca.init_background()

        self.assertEqual(str(context.exception), "Boom")

if __name__ == '__main__':
    unittest.main()
