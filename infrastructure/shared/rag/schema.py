"""In-memory BM25 retrieval over entity documents."""

from copy import deepcopy

from infrastructure.shared.rag.bm25 import rank


class SchemaRetriever:
    """Retrieve full entity definitions using entity-level lexical matches."""
    def retrieve(self, query: str, schema: dict, top_k: int = 10) -> dict:
        """Rebuild from the latest graph so newly added fields are searchable."""
        if top_k < 1:
            raise ValueError("top_k must be positive")
        # --- Extension point: retrieval document design -----------------------
        documents = {}
        for name, entity in schema["entities"].items():
            parts = [name, entity["description"]]
            for field_name, field in entity["fields"].items():
                parts.extend((field_name, field["description"]))
            documents[name] = " ".join(parts)
        if not documents:
            return {"matches": [], "entities": {}}

        # --- Key extension point: ranking and candidate budget ----------------
        # The shared BM25 engine also serves API retrieval. Replace rank() for
        # embeddings or hybrid retrieval, retaining {symbol, score} hits.
        # top_k limits the number of matched entities.
        # Foreign-key edges do not automatically add candidates.
        matches = rank(query, documents, top_k)
        selected = {match["symbol"].split(".")[0] for match in matches}

        # Return complete definitions only for entities selected by BM25 hits.
        return {
            "matches": matches,
            "entities": {name: deepcopy(entity) for name, entity in schema["entities"].items() if name in selected},
        }
