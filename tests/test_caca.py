import os
import unittest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

# Mock environment variables before importing anything
os.environ.setdefault("BOT_TOKEN", "dummy_token")
os.environ.setdefault("BOT_OWNER_ID", "12345")
os.environ.setdefault("LOG_CHAT_ID", "-10012345")
os.environ.setdefault("GROQ_API_KEY", "dummy_groq_key")
os.environ.setdefault("FONT_DIR", "./")

# Now import the module to test
from handlers import caca

class TestCaca(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_article_failure_logging(self):
        """
        Test that _fetch_article logs an error when an exception occurs.
        """
        # Mock get_http_session
        with patch("handlers.caca.get_http_session", new_callable=AsyncMock) as mock_get_session:
            # Mock the session object
            mock_session = MagicMock()
            mock_get_session.return_value = mock_session

            # Mock session.get to return an async context manager that raises an exception
            mock_get_ctx = MagicMock()
            mock_session.get.return_value = mock_get_ctx

            # __aenter__ must be awaitable and raise exception
            mock_get_ctx.__aenter__ = AsyncMock(side_effect=Exception("Network error"))
            mock_get_ctx.__aexit__ = AsyncMock(return_value=None)

            # Run the function
            with self.assertLogs("handlers.caca", level="ERROR") as cm:
                result = await caca._fetch_article("http://example.com")

            # Assertions
            self.assertIsNone(result)
            self.assertTrue(any("Network error" in o for o in cm.output))

if __name__ == "__main__":
    unittest.main()
