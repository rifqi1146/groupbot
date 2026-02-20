import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import ipaddress
import socket
import aiohttp
from handlers.networking import domain_cmd

class TestSSRF(unittest.IsolatedAsyncioTestCase):
    async def test_ssrf_blocked_private_ip(self):
        # Setup mocks
        update = AsyncMock()
        context = AsyncMock()
        context.args = ["internal.example.com"]

        # Mock socket.gethostbyname to return a private IP
        with patch('handlers.networking.socket.gethostbyname', return_value="127.0.0.1") as mock_gethost, \
             patch('handlers.networking.whois.whois') as mock_whois, \
             patch('handlers.networking.get_http_session', new_callable=AsyncMock) as mock_get_session:

            # session object itself doesn't need to be AsyncMock, but get_http_session is async
            session = MagicMock()
            mock_get_session.return_value = session

            # Execute
            await domain_cmd(update, context)

            # Assert that session.get was NOT called
            session.get.assert_not_called()

    async def test_ssrf_allowed_public_ip(self):
        # Setup mocks
        update = AsyncMock()
        context = AsyncMock()
        context.args = ["example.com"]

        # Mock socket.gethostbyname to return a public IP
        with patch('handlers.networking.socket.gethostbyname', return_value="93.184.216.34") as mock_gethost, \
             patch('handlers.networking.whois.whois') as mock_whois, \
             patch('handlers.networking.get_http_session', new_callable=AsyncMock) as mock_get_session:

            session = MagicMock()
            mock_get_session.return_value = session

            # Mock the response context manager
            # session.get() returns a context manager (cm)
            # async with cm: calls cm.__aenter__() which returns response
            mock_cm = MagicMock()
            mock_response = AsyncMock() # properties like .json() are async usually, but .status is attr
            mock_response.status = 200
            mock_response.headers = {"server": "ECS"}

            # __aenter__ must be an async function (AsyncMock)
            mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_cm.__aexit__ = AsyncMock(return_value=None)

            session.get.return_value = mock_cm

            # Execute
            await domain_cmd(update, context)

            # Assert that session.get WAS called with the IP address
            session.get.assert_called_once()
            args, kwargs = session.get.call_args

            # Verify the URL uses the IP address, not the domain
            self.assertEqual(args[0], "http://93.184.216.34")

            # Verify the Host header is set correctly
            self.assertIn("headers", kwargs)
            self.assertEqual(kwargs["headers"]["Host"], "example.com")
