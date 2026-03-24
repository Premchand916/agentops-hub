import unittest

from agents.workflow import WorkflowAgent
from rag.bm25_index import BM25Index
from rag.chunker import Chunk
from rag.vector_store import VectorStore


class BM25RegressionTests(unittest.TestCase):
    def test_hyphenated_error_codes_are_preserved(self) -> None:
        tokens = BM25Index()._tokenize("How do I fix VPN error E-4012?")

        self.assertIn("e-4012", tokens)
        self.assertIn("e4012", tokens)
        self.assertIn("4012", tokens)


class WorkflowRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = WorkflowAgent.__new__(WorkflowAgent)

    def test_find_tickets_query_is_trimmed_case_insensitively(self) -> None:
        tool_call = self.agent._rule_based_tool_call("Find tickets vpn")

        self.assertEqual(tool_call["tool_name"], "search_tickets")
        self.assertEqual(tool_call["arguments"]["query"], "vpn")

    def test_polite_search_ticket_prefix_is_removed(self) -> None:
        tool_call = self.agent._rule_based_tool_call("Please search ticket for vpn?")

        self.assertEqual(tool_call["tool_name"], "search_tickets")
        self.assertEqual(tool_call["arguments"]["query"], "vpn")


class VectorStoreRegressionTests(unittest.TestCase):
    def test_collection_info_uses_indexed_vectors_count_fallback(self) -> None:
        class _CollectionInfo:
            points_count = 17
            indexed_vectors_count = 17

        class _Client:
            def get_collection(self, _name: str):
                return _CollectionInfo()

        store = VectorStore.__new__(VectorStore)
        store.collection_name = "agentops_knowledge"
        store.client = _Client()

        info = store.get_collection_info()

        self.assertEqual(info["vectors_count"], 17)
        self.assertEqual(info["points_count"], 17)

    def test_point_ids_are_deterministic(self) -> None:
        store = VectorStore.__new__(VectorStore)
        chunk = Chunk(
            content="Reset the VPN client cache.",
            chunk_id="vpn-guide.md::chunk_0",
            chunk_index=0,
            metadata={"source": "rag/Documents/vpn-guide.md"},
        )

        first = store._build_point_id(chunk)
        second = store._build_point_id(chunk)

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
