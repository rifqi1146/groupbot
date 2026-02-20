import unittest
from utils.ai_utils import sanitize_ai_output

class TestAIUtils(unittest.TestCase):
    def test_sanitize_empty_input(self):
        """Test empty string and None input."""
        self.assertEqual(sanitize_ai_output(""), "")
        # The function signature says text: str, but strict typing is not enforced at runtime.
        # Assuming None should be handled gracefully if possible, or maybe it raises AttributeError if not text check fails?
        # The code starts with `if not text: return ""`. If text is None, `if not text` is true.
        self.assertEqual(sanitize_ai_output(None), "")

    def test_sanitize_newline_normalization(self):
        """Test normalization of newlines and break tags."""
        self.assertEqual(sanitize_ai_output("Line1\r\nLine2"), "Line1\nLine2")
        self.assertEqual(sanitize_ai_output("Line1\rLine2"), "Line1\nLine2")
        self.assertEqual(sanitize_ai_output("Line1<br>Line2"), "Line1\nLine2")
        self.assertEqual(sanitize_ai_output("Line1<br/>Line2"), "Line1\nLine2")
        self.assertEqual(sanitize_ai_output("Line1<BR>Line2"), "Line1\nLine2")
        self.assertEqual(sanitize_ai_output("Line1<br />Line2"), "Line1\nLine2")

    def test_sanitize_html_escaping(self):
        """Test HTML escaping."""
        # Note: HTML escaping happens early.
        self.assertEqual(sanitize_ai_output("<script>"), "&lt;script&gt;")
        self.assertEqual(sanitize_ai_output("&"), "&amp;")

    def test_sanitize_markdown_stripping(self):
        """Test removal of markdown style formatting."""
        self.assertEqual(sanitize_ai_output("**bold**"), "bold")
        self.assertEqual(sanitize_ai_output("*italic*"), "italic")
        self.assertEqual(sanitize_ai_output("__underline__"), "underline")
        self.assertEqual(sanitize_ai_output("~~strike~~"), "strike")
        # Combined
        self.assertEqual(sanitize_ai_output("**bold** and *italic*"), "bold and italic")

    def test_sanitize_blockquotes(self):
        """Test removal of blockquotes."""
        # Input "> Quote" becomes "&gt; Quote" after escape.
        # Regex is r"(?m)^&gt;\s*" which matches "&gt; " at start of line.
        self.assertEqual(sanitize_ai_output("> Quote"), "Quote")
        self.assertEqual(sanitize_ai_output(">Quote"), "Quote")
        self.assertEqual(sanitize_ai_output("Line1\n> Quote"), "Line1\nQuote")

    def test_sanitize_headers(self):
        """Test conversion of headers to bold HTML."""
        # # Header -> \n<b>Header</b>
        # strip() removes leading newline.
        self.assertEqual(sanitize_ai_output("# Header"), "<b>Header</b>")
        self.assertEqual(sanitize_ai_output("## Header 2"), "<b>Header 2</b>")
        self.assertEqual(sanitize_ai_output("### Header 3"), "<b>Header 3</b>")

    def test_sanitize_lists(self):
        """Test conversion of lists to bullets."""
        # Numbered list
        self.assertEqual(sanitize_ai_output("1. Item"), "• Item")
        # Dash list
        self.assertEqual(sanitize_ai_output("- Item"), "• Item")
        # Indented lists (regex allows whitespace at start)
        self.assertEqual(sanitize_ai_output("  1. Item"), "• Item")
        self.assertEqual(sanitize_ai_output("  - Item"), "• Item")

        # Multiple items
        # "1. Item1\n2. Item2"
        # 1. -> •
        # 2. -> •
        # and re.sub(r"\s*•\s*", "\n• ", text) ensures newline before bullet.
        result = sanitize_ai_output("1. Item1\n2. Item2")
        # Expect: "• Item1\n• Item2" (strip removes initial newline if any)
        # Detailed flow:
        # "1. Item1\n2. Item2"
        # -> "• Item1\n• Item2"
        # -> \s*•\s* -> \n•
        # So "• Item1" might become "\n• Item1".
        # "• Item2" might become "\n• Item2".
        # Result: "\n• Item1\n• Item2".
        # strip() -> "• Item1\n• Item2".
        self.assertEqual(result, "• Item1\n• Item2")

    def test_sanitize_horizontal_rules(self):
        """Test removal of horizontal rules."""
        self.assertEqual(sanitize_ai_output("---"), "")
        # Note: "Text\n---\nText" -> "Text\n\nText" which triggers definition list regex
        # if the first line is long enough. Use short words to avoid definition list trigger.
        self.assertEqual(sanitize_ai_output("a\n---\nb"), "a\n\nb")

    def test_sanitize_pipes(self):
        """Test pipe replacement."""
        self.assertEqual(sanitize_ai_output("a|b"), "a b")

    def test_sanitize_definition_lists(self):
        """Test definition list formatting."""
        # Regex: r"(?m)^\s*([A-Za-z0-9 _/().-]{2,})\s{2,}(.+)$"
        # Matches line starting with term (2+ chars) followed by 2+ spaces and definition.
        # Replaces with "• <b>Term</b>\n  Definition"
        # Then spaces are collapsed, so "  Definition" becomes " Definition"
        input_text = "Term  Definition"
        expected = "• <b>Term</b>\n Definition"
        self.assertEqual(sanitize_ai_output(input_text), expected)

    def test_sanitize_whitespace_cleanup(self):
        """Test collapsing of whitespace."""
        # Use symbols to avoid definition list trigger (regex matches alphanumeric and some symbols)
        self.assertEqual(sanitize_ai_output("!   !"), "! !")
        self.assertEqual(sanitize_ai_output("!\n\n\n\n!"), "!\n\n!")

if __name__ == "__main__":
    unittest.main()
