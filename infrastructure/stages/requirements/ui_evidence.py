"""Normalize published pages, states and recipes as evidence, never executable fixtures."""

import hashlib
import json

from infrastructure.stages.requirements.images import input_file, requirement_nodes

UI_EVIDENCE_INSTRUCTIONS = '''
ui_evidence supplies the source page/menu/state graph, contracts, recipes and capture
associations. Keep one page for multiple states, not a route for each screenshot.
For each page using source captures add source_page=canonical source page ID and
source_states={STATE_ID:{elements:[ELEMENT_ID],reason:"mapping to real controls/state"}}.
Map the current requirement's cited states, preserving earlier accepted mappings.
Use the source route unless explicit requirement evidence requires another; record an
alternative in route_decision={requirements:[REQ_ID],reason:"source conflict resolution"}.
State visibility belongs to declared frontend variables and actual component state.
Recipes describe observed user actions and popup/row identity, not executable code or
production business records. Do not replay original IDs, copy observed table values,
or inherit unrelated menus/features. Missing/uncollected states remain coverage gaps;
never remove a required feature because its screenshot was not collected. Source
framework/library detections describe the old application; generate React/Arco.
Source-library DOM roles and CSS classes are observed hints. Preserve names and roles
explicitly required by business prose/scenarios, while translating observed controls
into equivalent accessible Arco interactions. Do not require private Element Plus DOM.
'''


def compile_ui_evidence(raw, input_dir):
    result = {"enabled": False, "pages": {}, "states": {}, "links": [], "menu": [],
        "capture_states": {}, "source_hashes": {}, "diagnostics": []}
    def read(relative):
        p = input_file(input_dir, relative)
        data = p.read_bytes()
        result["source_hashes"][relative] = hashlib.sha256(data).hexdigest()
        return json.loads(data.decode("utf-8-sig"))
    if not (input_dir / "reference/ui/pages.json").is_file():
        return result
    pages = read("reference/ui/pages.json")
    index = read("reference/ui/index.json")
    result.update(enabled=True, menu=pages.get("menu", []), origin=pages.get("origin"))
    nodes = {n["id"] for n in requirement_nodes(raw)}
    for page in pages["pages"]:
        pid = page["id"]
        if pid in result["pages"]:
            raise ValueError(f"Duplicate UI source page {pid}")
        result["pages"][pid] = {key:page.get(key) for key in ("id","title","route","menu_path","status","reason")}
        result["pages"][pid]["states"] = []
        for state in page.get("states", []):
            sid = state["id"]
            if sid in result["states"]:
                raise ValueError(f"Duplicate UI source state {sid}")
            result["pages"][pid]["states"].append(sid)
            item = {**state, "page":pid, "captures":[], "observed_only":True}
            for folder in ("states", "recipes"):
                relative = f"reference/ui/{folder}/{sid}.json"
                if (input_dir / relative).is_file():
                    value = read(relative)
                    if value.get("state") != sid:
                        raise ValueError(f"UI {folder} file has wrong state: {sid}")
                    if folder == "states":
                        if value.get("page") != pid:
                            raise ValueError(f"UI state/page mismatch: {sid}")
                        item["contract"] = value.get("contract", {})
                        item["depends_on"] = value.get("depends_on", [])
                    else:
                        item["recipe"] = value
            result["states"][sid] = item
    for capture in index["captures"]:
        sid, cid = capture["state_id"], capture["id"]
        if sid not in result["states"]:
            raise ValueError(f"UI capture has an undeclared page state: {cid}/{sid}")
        result["capture_states"][cid] = sid
        result["states"][sid]["captures"].append(cid)
    for sid, state in result["states"].items():
        if state.get("parent") and state["parent"] not in result["states"]:
            result["diagnostics"].append({"code":"UI_PARENT_OUTSIDE_PUBLISHED_SCOPE","state":sid,"parent":state["parent"]})
        if not state.get("collected") or not state["captures"]:
            result["diagnostics"].append({"code":"UI_STATE_COVERAGE_GAP","state":sid})
    for link in index["node_links"]:
        if link["node_id"] not in nodes or link["capture_id"] not in result["capture_states"]:
            raise ValueError("UI link refers to an unknown requirement/capture")
        result["links"].append(link)
    path = "reference/ui/design-system.json"
    if (input_dir / path).is_file():
        observed = read(path)
        result["source_design_system"] = {**observed,"observed_only":True}
    return result


def ui_context(evidence, rid):
    if not evidence.get("enabled"):
        return {}
    links = [link for link in evidence["links"] if link["node_id"] == rid]
    states = {evidence["capture_states"][link["capture_id"]] for link in links}
    pages = {evidence["states"][sid]["page"] for sid in states}
    selected = set(states)
    for sid in list(states):
        seen = set()
        while sid in evidence["states"] and evidence["states"][sid].get("parent"):
            if sid in seen: raise ValueError("UI state parent cycle")
            seen.add(sid); sid = evidence["states"][sid]["parent"]
            if sid in evidence["states"]: selected.add(sid)
    def menu(items):
        result = []
        for item in items:
            if item.get("page") in pages: result.append(item)
            elif "children" in item:
                children = menu(item["children"])
                if children: result.append({**item,"children":children})
        return result
    return {"pages":{p:evidence["pages"][p] for p in sorted(pages)},
        "states":{s:evidence["states"][s] for s in sorted(selected)}, "cited_states":sorted(states),
        "declared_states":{s:{key:evidence["states"][s].get(key) for key in ("id","item","kind","collected","page")} for p in sorted(pages) for s in evidence["pages"][p]["states"]},
        "coverage_gaps":[d for d in evidence["diagnostics"] if d.get("state") in {s for p in pages for s in evidence["pages"][p]["states"]}],
        "menu":menu(evidence["menu"]), "links":links,
        "observed_design":{key:evidence.get("source_design_system",{}).get(key) for key in ("design_tokens","shell","templates")},
        "policy":UI_EVIDENCE_INSTRUCTIONS}


def validate_ui_mapping(design, context, rid):
    if not context:
        return
    mapped = set()
    from infrastructure.stages.frontend.ui.design import page_elements
    for pid,page in design["pages"].items():
        source = page.get("source_page")
        if source not in context["pages"]:
            continue
        expected = context["pages"][source]["route"]
        if page["route"] != expected:
            decision = page.get("route_decision", {})
            if rid not in decision.get("requirements",[]) or not decision.get("reason"):
                raise ValueError(f"{source}: source route {expected} requires explicit evidence for an alternative")
        for sid, binding in page.get("source_states", {}).items():
            if sid not in context["states"]:
                # Earlier owners may have mapped additional states of this page.
                if sid not in context["pages"][source]["states"]:
                    raise ValueError(f"Unknown source UI state mapping: {sid}")
                continue
            if context["states"][sid]["page"] != source or not binding.get("elements") or not set(binding["elements"]) <= set(page_elements(design,pid)):
                raise ValueError(f"Invalid source UI state mapping: {sid}")
            mapped.add(sid)
    missing = set(context["cited_states"]) - mapped
    if missing:
        raise ValueError(f"{rid}: map cited UI states to page.source_page/source_states: {sorted(missing)}")
