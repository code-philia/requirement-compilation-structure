"""Versioned component-use knowledge and deterministic BM25 retrieval."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from infrastructure.shared.rag.bm25 import rank
from infrastructure.shared.agent.discovery import ContextIndex
from infrastructure.stages.frontend.arco import COMPONENTS, VERSION
from infrastructure.utils.files import save_json, save_text

SOURCE = Path(__file__).with_name("arco-components.json")


class ComponentContextIndex(ContextIndex):
    """Add component discovery to design-only queries and retain the lookup trace."""
    def __init__(self, collections, arc_dir, stage, identity):
        super().__init__(lambda: {**collections(), "component":component_records()})
        self.arc_dir, self.stage, self.identity = arc_dir, stage, identity

    def query(self, request):
        result = super().query(request)
        if request.get("kind") == "component":
            self.arc_dir.mkdir(parents=True,exist_ok=True)
            with (self.arc_dir / "arco_queries.jsonl").open('a',encoding='utf-8') as stream:
                stream.write(json.dumps({"stage":self.stage,"identity":self.identity,
                    "request":request,"records":list(result.get("records",{})),
                    "candidates":result.get("candidates",[]),"missing":result.get("missing",[])},ensure_ascii=False)+'\n')
        return result


def component_records():
    records = {}
    for group in json.loads(SOURCE.read_text()):
        for name in group["components"]:
            if name not in COMPONENTS or name in records:
                raise ValueError(f"Unknown/duplicate Arco knowledge entry {name}")
            records[name] = {"id": name, "version": VERSION,
                "group":group["components"][0],
                **deepcopy({k:v for k,v in group.items() if k != "components"}),
                "related_components": group["components"], "callbacks": COMPONENTS[name],
                "guide": "frontend/arco-components/" + name + ".md",
                "types_directory": "frontend/arco-api/" + name.split('.')[0]}
    if set(records) != set(COMPONENTS):
        raise ValueError(f"Missing Arco knowledge: {sorted(set(COMPONENTS)-set(records))}")
    return records


def retrieve_components(requirement, elements=None, top_k=6):
    if top_k < 1:
        raise ValueError("Component retrieval top_k must be positive")
    records = component_records()
    explicit = sorted({node.get("component", {}).get("name") for node in (elements or {}).values()
        if node.get("component", {}).get("library") == "arco"})
    unknown = set(explicit) - set(records)
    if unknown:
        raise ValueError(f"Unsupported selected components: {sorted(unknown)}")
    # Do not query the whole model context: its catalog/backend evidence would bias retrieval.
    query = json.dumps({k:requirement.get(k) for k in ("name","description","steps")}, ensure_ascii=False)
    ranked = rank(query, {k:json.dumps(v, ensure_ascii=False) for k,v in records.items()},len(records))
    matches, groups = [], set()
    for match in ranked:
        group = records[match["symbol"]]["group"]
        if group not in groups:
            matches.append(match)
            groups.add(group)
        if len(matches) == top_k:
            break
    selected = list(dict.fromkeys([*explicit, *(m["symbol"] for m in matches)]))
    return {"method": "BM25+explicit_components", "version": VERSION,
        "knowledge_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "explicit": explicit, "matches": matches,
        "records": {name:deepcopy(records[name]) for name in selected}}


def record_retrieval(arc_dir, stage, identity, retrieved):
    path = arc_dir / "arco_retrieval.json"
    data = json.loads(path.read_text()) if path.is_file() else {}
    data.setdefault(stage, {})[identity] = retrieved
    save_json(path, data)


def publish_knowledge(output):
    records = component_records()
    save_json(output / "frontend/arco-components/index.json", records)
    for name, record in records.items():
        text = (f"# {name} — Arco React {VERSION}\n\n{record['description']}\n\n"
            f"适用：{record['use_when']}\n\n注意：{record['avoid_when']}\n\n"
            f"关键属性：{', '.join(record['props'])}\n\n"
            + '\n'.join('- '+p for p in record['patterns'])
            + '\n\n回调（参数名为编译器约定）：\n```json\n'
            + json.dumps(record['callbacks'], ensure_ascii=False, indent=2)
            + '\n```\n\n同组用法示例（非生产数据）：\n```tsx\n' + record['example']
            + '\n```\n\n只读类型目录：' + record['types_directory']
            + '\n\n官方参考：\n' + '\n'.join('- '+url for url in record['sources'])
            + '\n\n本文件是编译器整理的用途指南；准确属性以固定版本类型声明为准。\n')
        save_text(output / record["guide"], text)
    save_json(output / ".arc/arco_knowledge.json", {"version":VERSION,
        "sha256":hashlib.sha256(SOURCE.read_bytes()).hexdigest(), "components":list(records)})
