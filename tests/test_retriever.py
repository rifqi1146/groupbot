import asyncio
import unittest
from rag.retriever import retrieve_context

class TestRetriever(unittest.TestCase):
    def test_retrieve_context_happy_path(self):
        documents = [
            "Apple is a fruit",
            "Banana is also a fruit",
            "Carrot is a vegetable"
        ]
        query = "fruit"
        expected = ["Apple is a fruit", "Banana is also a fruit"]
        result = asyncio.run(retrieve_context(query, documents))
        self.assertEqual(result, expected)

    def test_retrieve_context_case_insensitivity(self):
        documents = ["Apple IS A FRUIT"]
        query = "apple"
        result = asyncio.run(retrieve_context(query, documents))
        self.assertEqual(result, ["Apple IS A FRUIT"])

    def test_retrieve_context_top_k(self):
        documents = [
            "Apple apple",
            "Apple banana",
            "Apple carrot"
        ]
        query = "apple"
        result = asyncio.run(retrieve_context(query, documents, top_k=2))
        self.assertEqual(len(result), 2)
        # All have score 1 because "apple" is in all of them.
        # Order should be preserved from the input list because Python's sort is stable.
        self.assertEqual(result, ["Apple apple", "Apple banana"])

    def test_retrieve_context_no_matches(self):
        documents = ["Apple", "Banana"]
        query = "Carrot"
        result = asyncio.run(retrieve_context(query, documents))
        self.assertEqual(result, [])

    def test_retrieve_context_empty_documents(self):
        documents = []
        query = "fruit"
        result = asyncio.run(retrieve_context(query, documents))
        self.assertEqual(result, [])

    def test_retrieve_context_multiple_query_words(self):
        documents = [
            "I like apples and bananas",
            "I like apples",
            "I like bananas"
        ]
        query = "apples bananas"
        # query_l.split() -> ["apples", "bananas"]
        # doc1: "apples" in doc1 (True), "bananas" in doc1 (True). score = 2.
        # doc2: "apples" in doc2 (True), "bananas" in doc2 (False). score = 1.
        # doc3: "apples" in doc3 (False), "bananas" in doc3 (True). score = 1.
        result = asyncio.run(retrieve_context(query, documents))
        self.assertEqual(result[0], "I like apples and bananas")
        self.assertEqual(len(result), 3)

if __name__ == "__main__":
    unittest.main()
