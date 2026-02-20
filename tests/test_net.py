import unittest
import asyncio
from unittest.mock import MagicMock, patch
import socket

# Import the functions to be tested
from handlers.net import _resolve_ips, _reverse_ptr

class TestNet(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_ips_success_ipv4(self):
        # Mock the loop and getaddrinfo
        with patch('handlers.net.asyncio.get_running_loop') as mock_get_loop:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            # Make getaddrinfo return a future
            future = asyncio.Future()
            future.set_result([
                (socket.AF_INET, 0, 0, '', ('1.2.3.4', 0)),
                (socket.AF_INET, 0, 0, '', ('1.2.3.4', 0)) # Duplicate
            ])
            mock_loop.getaddrinfo.return_value = future

            ips_v4, ips_v6 = await _resolve_ips("test.com")

            self.assertEqual(ips_v4, ['1.2.3.4'])
            self.assertEqual(ips_v6, [])
            mock_loop.getaddrinfo.assert_called_with("test.com", None)

    async def test_resolve_ips_success_ipv6(self):
        with patch('handlers.net.asyncio.get_running_loop') as mock_get_loop:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            future = asyncio.Future()
            future.set_result([
                (socket.AF_INET6, 0, 0, '', ('::1', 0, 0, 0))
            ])
            mock_loop.getaddrinfo.return_value = future

            ips_v4, ips_v6 = await _resolve_ips("test.com")

            self.assertEqual(ips_v4, [])
            self.assertEqual(ips_v6, ['::1'])

    async def test_resolve_ips_error(self):
        with patch('handlers.net.asyncio.get_running_loop') as mock_get_loop:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            # Make side_effect raise exception when awaited?
            # Or just raise exception immediately if the call itself fails?
            # loop.getaddrinfo is async, so it returns a coroutine.
            # If the coroutine raises, it happens when awaited.

            # To simulate raising in coroutine:
            future = asyncio.Future()
            future.set_exception(socket.gaierror("Name or service not known"))
            mock_loop.getaddrinfo.return_value = future

            ips_v4, ips_v6 = await _resolve_ips("invalid.com")

            self.assertEqual(ips_v4, [])
            self.assertEqual(ips_v6, [])

    async def test_reverse_ptr_success(self):
        with patch('handlers.net.asyncio.get_running_loop') as mock_get_loop:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            future = asyncio.Future()
            future.set_result(('example.com', 'http'))
            mock_loop.getnameinfo.return_value = future

            result = await _reverse_ptr("1.2.3.4")

            self.assertEqual(result, 'example.com')
            mock_loop.getnameinfo.assert_called_with(("1.2.3.4", 0), socket.NI_NAMEREQD)

    async def test_reverse_ptr_error(self):
        with patch('handlers.net.asyncio.get_running_loop') as mock_get_loop:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            future = asyncio.Future()
            future.set_exception(socket.herror("Unknown host"))
            mock_loop.getnameinfo.return_value = future

            result = await _reverse_ptr("1.2.3.4")

            self.assertIsNone(result)

if __name__ == "__main__":
    unittest.main()
