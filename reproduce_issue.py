import asyncio
import time
from unittest.mock import MagicMock, patch
import yt_dlp
from functools import partial

async def heartbeat():
    """Prints a dot every 0.1 seconds to show the event loop is running."""
    try:
        while True:
            print(".", end="", flush=True)
            await asyncio.sleep(0.1)
    except asyncio.CancelledError:
        pass

def blocking_work(ydl, query):
    # This function mimics the work inside the context manager
    return ydl.extract_info(query, download=False)

async def blocking_task():
    """Simulates the blocking yt_dlp call."""
    print("\nStarting blocking task...")

    # Mock yt_dlp to simulate blocking behavior
    with patch("yt_dlp.YoutubeDL") as MockYoutubeDL:
        mock_instance = MockYoutubeDL.return_value
        mock_instance.__enter__.return_value = mock_instance

        # Simulate a blocking network call taking 2 seconds
        def side_effect(*args, **kwargs):
            time.sleep(2)
            return {"entries": [{"title": "Test Video"}]}

        mock_instance.extract_info.side_effect = side_effect

        ydl_opts = {}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # This call blocks the event loop!
            info = ydl.extract_info("ytsearch5:test", download=False)

    print("\nBlocking task finished.")

async def non_blocking_task():
    """Simulates the non-blocking yt_dlp call using run_in_executor."""
    print("\nStarting non-blocking task...")

    # Mock yt_dlp to simulate blocking behavior
    with patch("yt_dlp.YoutubeDL") as MockYoutubeDL:
        mock_instance = MockYoutubeDL.return_value
        mock_instance.__enter__.return_value = mock_instance

        # Simulate a blocking network call taking 2 seconds
        def side_effect(*args, **kwargs):
            time.sleep(2)
            return {"entries": [{"title": "Test Video"}]}

        mock_instance.extract_info.side_effect = side_effect

        ydl_opts = {}
        loop = asyncio.get_running_loop()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # This call should run in a thread and NOT block the event loop
            info = await loop.run_in_executor(None, partial(ydl.extract_info, "ytsearch5:test", download=False))

    print("\nNon-blocking task finished.")

async def main():
    # 1. Verify blocking behavior
    print("--- Verifying Blocking Behavior ---")
    heartbeat_task = asyncio.create_task(heartbeat())
    start_time = time.time()
    await blocking_task()
    end_time = time.time()
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    print(f"Task took {end_time - start_time:.2f} seconds")

    # 2. Verify non-blocking behavior
    print("\n--- Verifying Non-Blocking Behavior ---")
    heartbeat_task = asyncio.create_task(heartbeat())
    start_time = time.time()
    await non_blocking_task()
    end_time = time.time()
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    print(f"Task took {end_time - start_time:.2f} seconds")

if __name__ == "__main__":
    asyncio.run(main())
