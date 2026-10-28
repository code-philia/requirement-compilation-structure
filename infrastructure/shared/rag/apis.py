"""Coarse API RAG over descriptions and field-level read/write obligations."""

from copy import deepcopy
from infrastructure.shared.rag.bm25 import rank


class ApiRetriever:
    """Coarse retrieval adapter for reusable canonical API Primitives."""
    def retrieve(self, query: str, apis: dict, top_k: int = 6) -> dict:
        # --- Extension point: semantic API reuse ------------------------------
        # Replace lexical relevance with embeddings, reranking, or a graph of
        # reusable operations. Retrieval never changes existing API identities.
        """Rank API descriptions and read/write symbols, returning hits and copies of the selected API definitions."""
        documents = {
            key: f"{key} {api['description']} {' '.join(api['read'])} {' '.join(api['write'])}"
            for key, api in apis.items()
        }
        matches = rank(query, documents, top_k)
        return {"matches": matches, "apis": {item["symbol"]: deepcopy(apis[item["symbol"]]) for item in matches}}
