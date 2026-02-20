import unittest
import asyncio
import logging
import os
from unittest.mock import AsyncMock, Mock, patch

# Set required environment variables before importing anything project-related
os.environ['BOT_TOKEN'] = 'mock_token'
os.environ['BOT_OWNER_ID'] = '12345,67890'
os.environ['LOG_CHAT_ID'] = '-1001234567890'
os.environ['API_ID'] = '123'
os.environ['API_HASH'] = 'mock_hash'
os.environ['SUPPORT_CHANNEL_ID'] = '-1001234567890'
os.environ['GEMINI_API_KEY'] = 'mock_gemini_key'
os.environ['GROQ_API_KEY'] = 'mock_groq_key'

# Assuming the handlers folder is in the python path
import sys
sys.path.append('.')

with patch('utils.config.GROQ_BASE', 'mock_base'), \
     patch('utils.config.GROQ_MODEL2', 'mock_model'), \
     patch('utils.config.GROQ_TIMEOUT', 10), \
     patch('utils.caca_db.load_groups', return_value=[]), \
     patch('utils.caca_db.get_mode', return_value='default'), \
     patch('utils.caca_memory.get_history', new_callable=AsyncMock, return_value=[]), \
     patch('utils.caca_memory.set_history', new_callable=AsyncMock), \
     patch('utils.caca_memory.cleanup', new_callable=AsyncMock), \
     patch('utils.caca_memory.init', new_callable=AsyncMock), \
     patch('utils.caca_db.init', new_callable=AsyncMock), \
     patch('utils.http.get_http_session', new_callable=AsyncMock):

    from handlers.caca import _typing_loop

class TestTypingLoop(unittest.IsolatedAsyncioTestCase):
    async def test_typing_loop_logs_exception(self):
        bot = AsyncMock()
        bot.send_chat_action.side_effect = Exception("Test Exception")
        chat_id = 123
        stop_event = asyncio.Event()

        # This should fail if no logs are emitted
        with self.assertLogs('handlers.caca', level='ERROR') as cm:
            await _typing_loop(bot, chat_id, stop_event)

        self.assertTrue(any("Test Exception" in output for output in cm.output))

if __name__ == '__main__':
    logging.basicConfig(level=logging.ERROR)
    unittest.main()
