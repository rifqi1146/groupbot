import sys
import os
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

# Add repo root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from handlers.music import music_callback
from telegram import Update, CallbackQuery, Message, User, Chat

class TestMusicHandler(unittest.IsolatedAsyncioTestCase):

    async def test_music_callback_success(self):
        # Mock dependencies
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch("yt_dlp.YoutubeDL") as MockYDL, \
             patch("glob.glob", return_value=["downloads/test_song.mp3"]), \
             patch("os.path.getmtime", return_value=1234567890), \
             patch("aiofiles.open", new_callable=MagicMock) as mock_aio_open, \
             patch("os.remove") as mock_remove:

            # Setup YDL mock
            mock_ydl_instance = MockYDL.return_value
            mock_ydl_instance.__enter__.return_value = mock_ydl_instance
            mock_ydl_instance.extract_info.return_value = {
                "title": "Test Song",
                "uploader": "Test Artist",
                "duration": 180,
                "ext": "mp3"
            }

            # Setup aiofiles mock
            mock_file = AsyncMock()
            mock_file.read.return_value = b"fake audio content"

            # Configure the async context manager
            # When aiofiles.open() is called, it returns a context manager.
            # The context manager's __aenter__ returns the file object.
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_file
            mock_ctx.__aexit__.return_value = None
            mock_aio_open.return_value = mock_ctx

            # Setup Update and Context
            update = MagicMock(spec=Update)
            query = MagicMock(spec=CallbackQuery)
            message = MagicMock(spec=Message)

            update.callback_query = query
            query.data = "music_download:VIDEO_ID"
            query.message = message
            query.answer = AsyncMock()
            query.edit_message_text = AsyncMock()
            message.chat_id = 12345
            message.reply_to_message.message_id = 67890
            message.delete = AsyncMock()

            context = MagicMock()
            context.bot.send_audio = AsyncMock()

            # Run the handler
            await music_callback(update, context)

            # Assertions

            # 1. Verify aiofiles.open was called instead of open
            mock_aio_open.assert_called_with("downloads/test_song.mp3", "rb")

            # 2. Verify file read was awaited
            mock_file.read.assert_awaited_once()

            # 3. Verify send_audio was called with correct arguments
            context.bot.send_audio.assert_awaited_once()
            _, kwargs = context.bot.send_audio.call_args

            self.assertEqual(kwargs["chat_id"], 12345)
            self.assertEqual(kwargs["audio"], b"fake audio content")
            self.assertEqual(kwargs["filename"], "test_song.mp3")
            self.assertEqual(kwargs["title"], "Test Song")

            # 4. Verify cleanup
            mock_remove.assert_called_with("downloads/test_song.mp3")

if __name__ == "__main__":
    unittest.main()
