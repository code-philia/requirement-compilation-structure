"""Page-first lexical retrieval returning complete canonical UI/data subtrees."""

import json

from infrastructure.stages.frontend.ui.design import page_context
from infrastructure.shared.rag.bm25 import rank


class PageRetriever:
    """Page-first retrieval adapter that returns complete reusable UI/data subtrees."""
    def retrieve(self, requirement: dict, design: dict, top_k: int = 3) -> dict:
        """Select explicit page/image matches plus lexical hits, returning each page with its complete UI/data subtree."""
        hints = {image.get("page") for image in requirement["images"].values() if image.get("page")}
        evidence = requirement["description"] + "\n" + json.dumps(requirement["steps"], ensure_ascii=False)
        explicit = [pid for pid, page in design["pages"].items() if pid in hints or page["name"] in hints
            or set(page["images"]) & set(requirement["images"])
            or (page["route"] != "/" and page["route"] in evidence)]
        documents = {pid: json.dumps({"id": pid, **page}, ensure_ascii=False) for pid, page in design["pages"].items()}
        matches = rank(json.dumps(requirement, ensure_ascii=False), documents, top_k)
        selected = list(dict.fromkeys([*explicit, *(item["symbol"] for item in matches)]))
        return {"explicit_matches": explicit, "matches": matches,
            "pages": {pid: page_context(design, pid) for pid in selected}}
