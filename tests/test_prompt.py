import unittest
from rag.prompt import build_rag_prompt

class TestPrompt(unittest.TestCase):
    def test_with_context(self):
        """Test that contexts are correctly joined and included in the prompt."""
        user_prompt = "What is KiyoshiBot?"
        contexts = ["Context 1", "Context 2"]
        expected_context = "Context 1\n\nContext 2"

        result = build_rag_prompt(user_prompt, contexts)

        self.assertIn(expected_context, result)
        self.assertIn(user_prompt, result)
        self.assertNotIn("Gunakan pengetahuanumum untuk jawab.", result)

    def test_empty_context(self):
        """Test that empty context triggers the fallback text."""
        user_prompt = "Tell me a joke."
        contexts = []

        result = build_rag_prompt(user_prompt, contexts)

        self.assertIn("Gunakan pengetahuanumum untuk jawab.", result)
        self.assertIn(user_prompt, result)

    def test_none_context(self):
        """Test that None context is handled safely (same as empty)."""
        user_prompt = "Is None supported?"
        contexts = None

        result = build_rag_prompt(user_prompt, contexts)

        self.assertIn("Gunakan pengetahuanumum untuk jawab.", result)
        self.assertIn(user_prompt, result)

    def test_prompt_inclusion(self):
        """Test that the user prompt is always included."""
        user_prompt = "This is a specific prompt."
        contexts = ["Some context"]

        result = build_rag_prompt(user_prompt, contexts)

        self.assertIn(user_prompt, result)

if __name__ == "__main__":
    unittest.main()
