import unittest
from rag.chunker import chunk_text

class TestChunker(unittest.TestCase):
    def test_chunk_text_empty(self):
        """Test that empty input returns an empty list."""
        self.assertEqual(chunk_text("", 100), [])

    def test_chunk_text_single_line_under_limit(self):
        """Test a single line that fits within the max_size."""
        self.assertEqual(chunk_text("hello", 10), ["hello"])

    def test_chunk_text_single_line_over_limit(self):
        """Test a single line that exceeds max_size.
        This currently exposes a bug where an empty string is prepended."""
        # The expected behavior is just the single line, split if logic allowed,
        # but current logic doesn't split lines, it just chunks by line.
        # So we expect ["hello world"] if max_size=5.
        self.assertEqual(chunk_text("hello world", 5), ["hello world"])

    def test_chunk_text_multiple_lines_under_limit(self):
        """Test multiple lines that fit in a single chunk."""
        text = "hello\nworld"
        # "hello\n" is 6 chars. "world" is 5 chars. Total 11 chars.
        # If max_size=20, it should fit in one chunk.
        self.assertEqual(chunk_text(text, 20), ["hello\nworld"])

    def test_chunk_text_multiple_lines_over_limit(self):
        """Test multiple lines where the second line exceeds the limit when added."""
        text = "hello\nworld"
        # "hello\n" is 6 chars.
        # If max_size=5.
        # "hello" (5) fits? Wait. logic is: len(buf) + len(line) > max_size.
        # loop 1: "hello" (5). buf="" (0). 0+5 > 5 False. buf="hello\n" (6).
        # loop 2: "world" (5). buf="hello\n" (6). 6+5 > 5 True.
        #   Append "hello\n".strip() -> "hello".
        #   buf="world\n".
        # End loop.
        # Append "world".
        self.assertEqual(chunk_text(text, 5), ["hello", "world"])

    def test_chunk_text_exact_limit(self):
        """Test behavior at exact max_size boundary."""
        text = "hello"
        # len("hello") is 5. max_size=5.
        # 0+5 > 5 False. buf="hello\n".
        # End loop. Append "hello".
        self.assertEqual(chunk_text(text, 5), ["hello"])

    def test_chunk_text_accumulate(self):
        """Test accumulation of multiple lines into chunks."""
        text = "a\nb\nc"
        # max_size=4.
        # 1. "a" (1). 0+1>4 False. buf="a\n" (2).
        # 2. "b" (1). 2+1>4 False. buf="a\nb\n" (4).
        # 3. "c" (1). 4+1>4 True.
        #    Append "a\nb". buf="c\n".
        # End loop. Append "c".
        self.assertEqual(chunk_text(text, 4), ["a\nb", "c"])

if __name__ == "__main__":
    unittest.main()
