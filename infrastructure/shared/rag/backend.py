"""Union of lexical and mode-aware obligation retrieval for backend contracts."""

from copy import deepcopy
import json

from infrastructure.shared.rag.bm25 import rank


class BackendRetriever:
    def retrieve(self, query: str, required: dict, design: dict, top_k: int = 6) -> dict:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        result = {"apis": {}, "modules": {}, "matches": {}}
        for kind in ("apis", "modules"):
            records = design[kind]
            documents = {}
            for identity, record in records.items():
                documents[identity] = identity + " " + json.dumps(record, ensure_ascii=False)
            lexical = rank(query, documents, top_k)
            overlap = []
            for identity, record in records.items():
                shared = 0
                total = 0
                for mode in ("read", "write"):
                    wanted, offered = set(required[mode]), set(record[mode])
                    shared += len(wanted & offered)
                    total += len(wanted | offered)
                if shared:
                    overlap.append({"symbol": identity, "score": shared / total,
                        "shared_read": sorted(set(required["read"]) & set(record["read"])),
                        "shared_write": sorted(set(required["write"]) & set(record["write"]))})
            overlap.sort(key=lambda item: (-item["score"], item["symbol"]))
            selected = set()
            for match in lexical + overlap[:top_k]:
                selected.add(match["symbol"])
            for identity in sorted(selected):
                result[kind][identity] = deepcopy(records[identity])
            result["matches"][kind] = {"bm25": lexical, "obligation": overlap[:top_k]}
        # Include dependencies and their callers so shared updates can coordinate contracts.
        pending = list(result["apis"].values()) + list(result["modules"].values())
        while pending:
            record = pending.pop()
            for identity in record["callees"] + record["callers"]:
                kind = "apis" if identity in design["apis"] else "modules"
                if identity not in result[kind]:
                    neighbor = deepcopy(design[kind][identity])
                    result[kind][identity] = neighbor
                    pending.append(neighbor)
        return result
