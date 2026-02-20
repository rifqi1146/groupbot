import os
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
import asyncio

# Mock environment variables BEFORE importing utils.config
os.environ["BOT_TOKEN"] = "test_token"
os.environ["BOT_OWNER_ID"] = "12345"
os.environ["LOG_CHAT_ID"] = "123"
os.environ["GEMINI_API_KEY"] = "test_gemini_key_initial"

# Now we can import the module to test
from handlers.gemini import ask_ai_gemini

class TestGeminiSecurity(unittest.TestCase):
    @patch("handlers.gemini.GEMINI_API_KEY", "test_api_key")
    @patch("handlers.gemini.get_http_session")
    def test_ask_ai_gemini_uses_header_auth(self, mock_get_session):
        async def run_test():
            # Mock session and response
            mock_session = MagicMock() # Changed from AsyncMock to MagicMock for session because we are mocking .post return value directly
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json.return_value = {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "Hello, world!"}]
                        }
                    }
                ]
            }
            # Mock context manager for session.post
            mock_post = MagicMock()
            mock_post.__aenter__ = AsyncMock(return_value=mock_response)
            mock_post.__aexit__ = AsyncMock(return_value=None)

            mock_session.post.return_value = mock_post
            mock_get_session.return_value = mock_session

            # Run the function
            prompt = "Hello"
            success, response = await ask_ai_gemini(prompt)

            # Assertions
            if not success:
                print(f"FAILED with error: {response}")

            self.assertTrue(success, f"Function returned False: {response}")
            self.assertEqual(response, "Hello, world!")

            # Verify session.post was called
            mock_session.post.assert_called_once()

            # Get the call arguments
            args, kwargs = mock_session.post.call_args
            url = args[0]
            headers = kwargs.get("headers", {})

            # Security Checks
            # 1. API Key should NOT be in the URL
            self.assertNotIn("key=test_api_key", url, "API Key found in URL query parameters!")

            # 2. API Key SHOULD be in the headers
            self.assertIn("x-goog-api-key", headers, "API Key missing from headers!")
            self.assertEqual(headers["x-goog-api-key"], "test_api_key", "Incorrect API Key in headers!")

        asyncio.run(run_test())

if __name__ == "__main__":
    unittest.main()
