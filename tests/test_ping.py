import unittest
from unittest.mock import AsyncMock, MagicMock
from handlers.ping import ping_cmd
from telegram import Update
from telegram.ext import ContextTypes

class TestPing(unittest.IsolatedAsyncioTestCase):
    async def test_ping_cmd(self):
        # Mock Update and Context
        update = MagicMock(spec=Update)
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

        # Mock update.message
        message = MagicMock()
        # reply_text is async so return_value should be awaitable or it is an AsyncMock
        # In python-telegram-bot reply_text is async.
        # But here we mock it. If the code awaits it, the mock must be awaitable.
        message.reply_text = AsyncMock()

        update.message = message

        # Mock reply_text return value (which is the message object that gets edited)
        reply_msg = MagicMock()
        # edit_text is async
        reply_msg.edit_text = AsyncMock()

        message.reply_text.return_value = reply_msg

        # Call the function
        await ping_cmd(update, context)

        # Verify reply_text was called
        message.reply_text.assert_called_once_with("🏓 Pong...")

        # Verify edit_text was called
        # The edit_text is called on the object returned by reply_text
        reply_msg.edit_text.assert_called_once()
        args, kwargs = reply_msg.edit_text.call_args
        self.assertIn("Pong!", args[0])
        self.assertIn("Latency:", args[0])
        self.assertEqual(kwargs['parse_mode'], "HTML")

if __name__ == '__main__':
    unittest.main()
