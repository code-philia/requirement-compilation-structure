"""Page-aware coarse retrieval of reusable triggers and event definitions."""

from copy import deepcopy
import json

from infrastructure.shared.rag.bm25 import rank


class InteractionRetriever:
    """Retrieve existing events using page identity and lexical requirement relevance."""
    def retrieve(self, requirement, pages, interactions, top_k=6):
        """Include events already attached to the selected pages plus lexical hits, returning their events and triggers."""
        nodes = {uid for page in pages.values() for uid in page["elements"]}
        direct = {tr["action"] for tr in interactions["triggers"].values() if tr["source"] in nodes}
        documents = {eid: eid + " " + json.dumps(event, ensure_ascii=False) for eid, event in interactions["events"].items()}
        matches = rank(json.dumps(requirement, ensure_ascii=False), documents, top_k)
        selected = direct | {item["symbol"] for item in matches}
        return {"matches": matches,
            "events": {eid: deepcopy(event) for eid, event in interactions["events"].items() if eid in selected},
            "triggers": {tid: deepcopy(tr) for tid, tr in interactions["triggers"].items() if tr["action"] in selected}}
