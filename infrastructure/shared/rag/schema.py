"""In-memory BM25 retrieval over entity and field documents."""

from copy import deepcopy

from infrastructure.shared.rag.bm25 import rank, tokenize


class SchemaRetriever:
    """Retrieve full entity definitions using entity- and field-level lexical matches."""
    def retrieve(self, query: str, schema: dict, top_k: int = 6) -> dict:
        """Rebuild from the latest graph so newly added fields are searchable."""
        if top_k < 1:
            raise ValueError("top_k must be positive")
        # --- Extension point: retrieval document design -----------------------
        # Entity-level and field-level documents trade broad context for precise
        # matches. Experiment with their granularity and included properties.
        documents = {}
        for name, entity in schema["entities"].items():
            documents[name] = f"{name} {entity['description']} {' '.join(entity['fields'])}"
            for field_name, field in entity["fields"].items():
                symbol = f"{name}.{field_name}"
                text = f"{symbol} {entity['description']} {field['description']} {' '.join(field['constraints'])}"
                documents[symbol] = text
        if not documents:
            return {"matches": [], "entities": {}}

        # --- Key extension point: ranking and candidate budget ----------------
        # The shared BM25 engine also serves API retrieval. Replace rank() for
        # embeddings or hybrid retrieval, retaining {symbol, score} hits.
        # top_k limits hits; matched fields return their owner's full definition.
        # Foreign-key edges do not automatically add candidates.
        matches = rank(query, documents, top_k)
        selected = {match["symbol"].split(".")[0] for match in matches}

        # Return complete definitions only for entities selected by BM25 hits.
        return {
            "matches": matches,
            "entities": {name: deepcopy(entity) for name, entity in schema["entities"].items() if name in selected},
        }
