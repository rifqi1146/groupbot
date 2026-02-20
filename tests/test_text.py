import unittest
from utils.text import bold, italic, underline, code, pre, mono, link

class TestTextFormatting(unittest.TestCase):
    def test_bold(self):
        self.assertEqual(bold("Hello"), "<b>Hello</b>")
        self.assertEqual(bold("<script>"), "<b>&lt;script&gt;</b>")
        self.assertEqual(bold(""), "<b></b>")

    def test_italic(self):
        self.assertEqual(italic("World"), "<i>World</i>")
        self.assertEqual(italic("Wait & See"), "<i>Wait &amp; See</i>")
        self.assertEqual(italic(""), "<i></i>")

    def test_underline(self):
        self.assertEqual(underline("Important"), "<u>Important</u>")
        self.assertEqual(underline('"Quote"'), "<u>&quot;Quote&quot;</u>")
        self.assertEqual(underline(""), "<u></u>")

    def test_code(self):
        self.assertEqual(code("print('hi')"), "<code>print(&#x27;hi&#x27;)</code>")
        self.assertEqual(code("x < y"), "<code>x &lt; y</code>")
        self.assertEqual(code(""), "<code></code>")

    def test_pre(self):
        self.assertEqual(pre("Line 1\nLine 2"), "<pre>Line 1\nLine 2</pre>")
        self.assertEqual(pre("<div>"), "<pre>&lt;div&gt;</pre>")
        self.assertEqual(pre(""), "<pre></pre>")

    def test_mono(self):
        self.assertEqual(mono("Typewriter"), "<tt>Typewriter</tt>")
        self.assertEqual(mono("1 > 0"), "<tt>1 &gt; 0</tt>")
        self.assertEqual(mono(""), "<tt></tt>")

    def test_link(self):
        self.assertEqual(link("Google", "https://google.com"), '<a href="https://google.com">Google</a>')
        self.assertEqual(link("<Safety First>", "https://example.com?q=1&p=2"), '<a href="https://example.com?q=1&amp;p=2">&lt;Safety First&gt;</a>')
        self.assertEqual(link("", ""), '<a href=""></a>')

if __name__ == '__main__':
    unittest.main()
