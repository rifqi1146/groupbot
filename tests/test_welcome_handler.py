import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Set env vars before importing handlers to bypass checks
os.environ.setdefault("BOT_TOKEN", "dummy_token")
os.environ.setdefault("BOT_OWNER_ID", "12345,67890")
os.environ.setdefault("LOG_CHAT_ID", "112233")

# Mock sqlite3 entirely before importing handlers.welcome to prevent file creation
mock_sqlite = MagicMock()
mock_sqlite.IntegrityError = Exception
sys.modules["sqlite3"] = mock_sqlite

# Now import the module to test
import handlers.welcome

class TestWelcomeHandler(unittest.IsolatedAsyncioTestCase):
    async def test_welcome_handler_logs_error_on_restriction_failure(self):
        # Mock Update
        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.new_chat_members = [MagicMock(id=67890, username="testuser")]

        # Ensure reply_text is awaitable and returns a mock message
        mock_sent_message = MagicMock()
        mock_sent_message.message_id = 999
        update.message.reply_text = AsyncMock(return_value=mock_sent_message)

        # Mock Context
        context = MagicMock()
        context.bot.restrict_chat_member = AsyncMock(side_effect=Exception("Restriction failed"))
        # Mock other bot methods to avoid errors down the line
        context.bot.get_user_profile_photos = AsyncMock(return_value=MagicMock(total_count=0))
        context.bot.send_photo = AsyncMock()
        context.bot.username = "testbot"

        # Mock WELCOME_ENABLED_CHATS to include our chat
        with patch("handlers.welcome.WELCOME_ENABLED_CHATS", {12345}):
             # Mock the logger. We expect 'log' to exist in handlers.welcome.
            with patch("handlers.welcome.log") as mock_log:
                await handlers.welcome.welcome_handler(update, context)

                # Verify restrict_chat_member was called
                context.bot.restrict_chat_member.assert_awaited()

                # Verify logger.warning was called with the expected message
                args, _ = mock_log.warning.call_args
                self.assertIn("Restriction failed", args[0])
                self.assertIn("67890", str(args[0]))
                self.assertIn("12345", str(args[0]))

if __name__ == "__main__":
    unittest.main()
