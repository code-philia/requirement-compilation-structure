"""Bounded Rich views of existing compiler artifacts; no model or acceptance logic."""

from rich import box
from rich.console import Group
from rich.table import Table
from rich.text import Text
from rich.tree import Tree


ARTIFACTS = {
    "requirements": "Requirements", "db_schema": "DB schema",
    "db_obligations": "DB obligations", "backend_apis": "Backend APIs",
    "backend_contracts": "API contracts", "ui_design": "Frontend UI",
    "ui_interactions": "Frontend interactions",
}
LIMIT = 36


def text(value, limit=220):
    """Treat all artifact strings as literal text, with bounded cell sizes."""
    value = str(value)
    return Text(value[:limit] + ("…" if len(value) > limit else ""))


def table(*headers):
    result = Table(expand=True, header_style="bold cyan", border_style="dim", box=box.ROUNDED, show_lines=False)
    for header in headers:
        result.add_column(header, overflow="fold")
    return result


def joined(values):
    return ", ".join(map(str, values)) or "—"


def changed(before, key, value):
    if before is None:
        return Text("+", style="green")
    if key not in before:
        return Text("+", style="green")
    return Text("~", style="yellow") if before[key] != value else Text("·", style="dim")


def inventory(kind, data):
    """Flatten semantic records only for visual change accounting."""
    if kind == "requirements":
        result, pending = {}, [data]
        while pending and len(result) < 10000:
            node = pending.pop()
            if not isinstance(node, dict) or node.get("id") in result:
                continue
            result[node.get("id", "?")] = {k: v for k, v in node.items() if k != "children"}
            pending.extend(node.get("children", []))
        return result
    if kind == "db_schema":
        return {f"{entity}.{field}": value for entity, record in data.get("entities", {}).items()
            for field, value in record.get("fields", {}).items()}
    keys = {"db_obligations": ("requirements", "steps"), "backend_apis": ("apis",),
        "backend_contracts": ("apis",), "ui_design": ("pages", "elements", "bindings"),
        "ui_interactions": ("triggers", "events", "contracts")}.get(kind, ())
    return {f"{registry}:{key}": value for registry in keys for key, value in data.get(registry, {}).items()}


def render_artifact(kind, data, previous=None, context=None):
    """Render accepted snapshots or proposals, tolerating incomplete proposal shapes."""
    views = []
    old = inventory(kind, previous) if previous is not None else None
    current = inventory(kind, data)
    if old is not None:
        added = current.keys() - old.keys()
        removed = old.keys() - current.keys()
        updated = [key for key in current.keys() & old.keys() if current[key] != old[key]]
        views.append(Text(f"+ {len(added)} added   ~ {len(updated)} changed   - {len(removed)} removed", style="bold"))
        if removed:
            views.append(Text("Removed: " + joined(sorted(removed))[:400], style="red"))
    if kind == "requirements":
        root = Tree(text(f"{data.get('id', 'ROOT')} · {data.get('name', '')}"), guide_style="cyan")
        pending = [(root, child, 1) for child in reversed(data.get("children", []))]
        seen = set()
        while pending and len(seen) < LIMIT:
            parent, node, depth = pending.pop()
            key = node.get("id", "?")
            if key in seen:
                continue
            seen.add(key)
            branch = parent.add(text(f"{key} · {node.get('name', '')}  ({len(node.get('scenarios', []))} scenarios)"))
            if depth < 8:
                pending.extend((branch, child, depth + 1) for child in reversed(node.get("children", [])))
        if pending:
            root.add("… more requirements in artifact")
        views.append(root)
    elif kind == "db_schema":
        view = table("Δ", "Entity.field", "Type", "Properties")
        for key, field in list(current.items())[:LIMIT]:
            flags = [name for name, flag in (("PK", "primary_key"), ("UNIQUE", "unique"), ("NULL", "nullable")) if field.get(flag)]
            if field.get("nullable") is False:
                flags.append("NOT NULL")
            if field.get("references"):
                flags.append("→ " + str(field["references"]))
            view.add_row(changed(old, key, field), text(key), text(field.get("type", "?")), text(joined(flags)))
        views.append(view)
        relations = table("Requirement", "Related DB fields")
        for rid, fields in list(data.get("requirements", {}).items())[:12]:
            relations.add_row(text(rid), text(joined(fields), 500))
        if relations.row_count:
            views.append(relations)
    elif kind == "db_obligations":
        view = table("Requirement", "READ", "WRITE")
        for rid, record in list(data.get("requirements", {}).items())[:LIMIT]:
            view.add_row(text(rid), text(joined(record.get("read", [])), 500), text(joined(record.get("write", [])), 500))
        views.append(view)
    elif kind in {"backend_apis", "backend_contracts"}:
        view = table("Δ", "API / HTTP / owners", "DB effects")
        for aid, api in list(data.get("apis", {}).items())[:LIMIT]:
            signature = api.get("signature", {})
            owners = [rid for rid, ids in data.get("requirements", {}).items() if aid in ids]
            endpoint = f"{signature.get('method', '')} {signature.get('path', '')}"
            view.add_row(changed(old, "apis:" + aid, api), text(aid + "\n" + endpoint + "\n" + joined(owners)),
                Text.assemble("READ  ", text(joined(api.get("read", []))), "\nWRITE ", text(joined(api.get("write", [])))))
        views.append(view)
        if kind == "backend_contracts":
            contracts = table("API", "P · Preconditions", "Q · Postconditions")
            for aid, api in list(data.get("apis", {}).items())[:12]:
                def conditions(key):
                    return "\n".join(str(item.get("description", item)) if isinstance(item, dict) else str(item)
                        for item in api.get(key, [])) or "—"
                contracts.add_row(text(aid), text(conditions("precondition"), 600), text(conditions("postcondition"), 600))
            views.append(contracts)
    elif kind == "ui_design":
        root = Tree("Pages → UI elements → data bindings", guide_style="cyan")
        elements = data.get("elements", {})
        children = {}
        for eid, element in elements.items():
            children.setdefault(element.get("parent"), []).append(eid)
        count = 0
        for pid, page in list(data.get("pages", {}).items())[:12]:
            branch = root.add(text(f"{pid} · {page.get('route', '')} · {page.get('name', '')}"))
            pending, seen = [(branch, page.get("root"), 0)], set()
            while pending and count < LIMIT:
                parent, eid, depth = pending.pop()
                if eid in seen or eid not in elements:
                    continue
                seen.add(eid)
                count += 1
                element = elements[eid]
                prop = element.get("prop", {})
                label = prop.get("text", prop.get("label", ""))
                node = parent.add(text(f"{eid} [{element.get('type', '?')}] {label}"))
                if element.get("data"):
                    node.add(text("data → " + joined(element["data"])))
                if depth < 7:
                    pending.extend((node, child, depth + 1) for child in reversed(children.get(eid, [])))
            if pending:
                branch.add("… more elements in artifact")
        views.append(root)
        ownership = table("Requirement", "UI roots / controls")
        for rid, ids in list(data.get("requirements", {}).items())[:12]:
            ownership.add_row(text(rid), text(joined(ids), 400))
        if ownership.row_count:
            views.append(ownership)
        bindings = table("Data binding", "Type", "Source")
        for name, record in list(data.get("bindings", {}).items())[:12]:
            bindings.add_row(text(name), text(record.get("dtype", "?")), text(record.get("source", "—")))
        if bindings.row_count:
            views.append(bindings)
    elif kind == "ui_interactions":
        root = Tree("UI trigger → event → API → DB fields", guide_style="cyan")
        backend = (context or {}).get("backend_contracts", (context or {}).get("backend_apis", {})).get("apis", {})
        for tid, trigger in list(data.get("triggers", {}).items())[:LIMIT]:
            owners = [rid for rid, ids in data.get("requirements", {}).items() if tid in ids]
            branch = root.add(text(f"{tid} · {trigger.get('source')} / {trigger.get('event')} · {joined(owners)}"))
            eid = trigger.get("action")
            event = data.get("events", {}).get(eid, {})
            node = branch.add(text(eid))
            for action in event.get("actions", [])[:8]:
                if action.get("kind") == "api":
                    aid = action.get("api")
                    api = backend.get(aid, {})
                    api_node = node.add(text("API → " + str(aid)))
                    if api:
                        api_node.add(text("READ  " + joined(api.get("read", []))))
                        api_node.add(text("WRITE " + joined(api.get("write", []))))
                elif action.get("kind") == "navigate":
                    node.add(text("Navigate → " + str(action.get("page"))))
                else:
                    node.add(text(f"{action.get('kind', '')} · {action.get('description', '')}"))
            if event.get("write"):
                node.add(text("Frontend writes → " + joined(event["write"])))
        views.append(root)
    else:
        view = table("Field", "Value")
        for key, value in list(data.items())[:16]:
            view.add_row(text(key), text(value, 500))
        views.append(view)
    if len(current) > LIMIT:
        views.append(Text(f"{len(current)} records total · bounded preview · complete artifact retained", style="dim"))
    return Group(*views)


def proposal_kind(data):
    """Select a view from known stage shapes without interpreting business meaning."""
    if not isinstance(data, dict):
        return None
    for key, kind in (("entities", "db_schema"), ("apis", "backend_apis"), ("pages", "ui_design"),
            ("triggers", "ui_interactions"), ("children", "requirements")):
        if key in data:
            return kind
    return None
