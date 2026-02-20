import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import os
import asyncio
import sys

# Set dummy env vars before importing anything that might need them
os.environ["BOT_TOKEN"] = "dummy_token"
os.environ["BOT_OWNER_ID"] = "123456"
os.environ["LOG_CHAT_ID"] = "-1001234567890"

# Add repo root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from handlers.cookies import cookies_cmd

class TestCookiesHandler(unittest.TestCase):
    def setUp(self):
        self.test_file = "test_cookies_source.txt"
        with open(self.test_file, "w") as f:
            f.write("# Netscape HTTP Cookie File\n.google.com\tTRUE\t/\tFALSE\t1234567890\tname\tvalue")
        self.mock_cookies_path = "mock_cookies.txt"

    def tearDown(self):
        if os.path.exists(self.test_file):
            os.remove(self.test_file)
        if os.path.exists(self.mock_cookies_path):
            os.remove(self.mock_cookies_path)
        if os.path.exists(self.mock_cookies_path + ".uploading"):
            os.remove(self.mock_cookies_path + ".uploading")

    def test_cookies_cmd_success(self):
        async def run_test():
            update = MagicMock()
            context = MagicMock()

            # Setup user
            update.effective_user.id = 123456
            update.message.document.file_size = 100

            # Mock file download
            tg_file = AsyncMock()
            # properly await get_file
            update.message.document.get_file = AsyncMock(return_value=tg_file)

            async def download_side_effect(custom_path=None, **kwargs):
                # simulate download by copying the test file
                with open(self.test_file, "rb") as src, open(custom_path, "wb") as dst:
                    dst.write(src.read())

            tg_file.download_to_drive.side_effect = download_side_effect
            update.message.reply_text = AsyncMock()

            # Patch OWNER_ID (which is already imported in cookies.py)
            # Since OWNER_ID is imported in handlers/cookies.py, patching handlers.cookies.OWNER_ID works
            with patch("handlers.cookies.OWNER_ID", {123456}), \
                 patch("handlers.cookies.COOKIES_PATH", self.mock_cookies_path), \
                 patch("handlers.cookies.COOKIES_DIR", os.path.dirname(os.path.abspath(self.mock_cookies_path))):

                await cookies_cmd(update, context)

            # Verify reply
            update.message.reply_text.assert_called()
            args, kwargs = update.message.reply_text.call_args
            self.assertIn("Cookies successfully updated", args[0])

            # Verify file exists
            self.assertTrue(os.path.exists(self.mock_cookies_path))

        asyncio.run(run_test())

if __name__ == "__main__":
    unittest.main()
