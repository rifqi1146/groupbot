import unittest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import logging
import os

# Set fake env vars for testing BEFORE importing handlers
os.environ["BOT_TOKEN"] = "123:ABC"
os.environ["BOT_OWNER_ID"] = "12345"
os.environ["LOG_CHAT_ID"] = "67890"

# Set up logging capture
logging.basicConfig(level=logging.INFO)

from handlers import caca

class TestCacaHandler(unittest.TestCase):

    def setUp(self):
        # Create a mock update and context
        self.update = MagicMock()
        self.context = MagicMock()
        self.message = MagicMock()
        self.user = MagicMock()
        self.chat = MagicMock()

        self.user.id = 12345
        self.chat.id = 67890
        self.chat.type = "private"

        self.message.from_user = self.user
        self.message.chat = self.chat
        self.message.text = "/caca search failure"
        self.message.reply_to_message = None

        # Ensure reply_text is awaitable
        self.message.reply_text = AsyncMock()

        self.update.message = self.message
        self.update.effective_chat = self.chat

        self.context.args = ["search", "failure"]
        self.context.bot = MagicMock()
        self.context.bot.send_chat_action = AsyncMock()

    @patch('handlers.caca.caca_db')
    @patch('handlers.caca.caca_memory')
    @patch('handlers.caca.get_http_session', new_callable=AsyncMock)
    @patch('handlers.caca.google_search', new_callable=AsyncMock)
    @patch('handlers.caca.split_message')
    def test_meta_query_search_failure_logs_error(self, mock_split, mock_search, mock_session, mock_memory, mock_db):
        # Setup mocks
        mock_db.load_groups.return_value = []
        mock_db.get_mode.return_value = "default"

        # Async mocks require future return value or AsyncMock
        mock_memory.get_history = AsyncMock(return_value=[])
        mock_memory.set_history = AsyncMock()
        mock_memory.clear = AsyncMock()
        mock_memory.clear_last_message_id = AsyncMock()
        mock_memory.set_last_message_id = AsyncMock()

        # Simulate Google Search Failure (Exception)
        mock_search.side_effect = Exception("Search API Down")

        # Simulate AI response success so the function completes
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={
            "choices": [{"message": {"content": "AI Response"}}]
        })

        # Setup session mock
        session_mock = MagicMock()
        mock_session.return_value = session_mock

        post_ctx = MagicMock()
        post_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        post_ctx.__aexit__ = AsyncMock(return_value=None)

        session_mock.post.return_value = post_ctx

        mock_split.return_value = ["AI Response"]

        # Run the function
        # We need to capture logs
        with self.assertLogs('handlers.caca', level='ERROR') as cm:
            asyncio.run(caca.meta_query(self.update, self.context))

            # Assert that the error was logged
            self.assertTrue(any("Search API Down" in log for log in cm.output), "Expected error log not found")

    @patch('handlers.caca.caca_db')
    @patch('handlers.caca.caca_memory')
    @patch('handlers.caca.get_http_session', new_callable=AsyncMock)
    @patch('handlers.caca.google_search', new_callable=AsyncMock)
    @patch('handlers.caca.split_message')
    def test_meta_query_search_failure_logs_warning(self, mock_split, mock_search, mock_session, mock_memory, mock_db):
        # Setup mocks
        mock_db.load_groups.return_value = []
        mock_db.get_mode.return_value = "default"

        mock_memory.get_history = AsyncMock(return_value=[])
        mock_memory.set_history = AsyncMock()
        mock_memory.clear = AsyncMock()
        mock_memory.clear_last_message_id = AsyncMock()
        mock_memory.set_last_message_id = AsyncMock()

        # Simulate Google Search Failure (ok=False)
        mock_search.return_value = (False, "API Quota Exceeded")
        mock_search.side_effect = None

        # Simulate AI response success
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={
            "choices": [{"message": {"content": "AI Response"}}]
        })

        # Setup session mock
        session_mock = MagicMock()
        mock_session.return_value = session_mock

        post_ctx = MagicMock()
        post_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        post_ctx.__aexit__ = AsyncMock(return_value=None)

        session_mock.post.return_value = post_ctx

        mock_split.return_value = ["AI Response"]

        # Run the function and capture logs
        with self.assertLogs('handlers.caca', level='WARNING') as cm:
            asyncio.run(caca.meta_query(self.update, self.context))

            # Verify warning log
            self.assertTrue(any("API Quota Exceeded" in log for log in cm.output), "Expected warning log not found")

        # Verify AI call was made despite search failure
        session_mock.post.assert_called()

if __name__ == '__main__':
    unittest.main()
