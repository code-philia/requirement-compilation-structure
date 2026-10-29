"""Small model contexts without reducing the compiler's implementation or test scope.

Event creation sees one event. Requirement repair sees every required handler.
Source dependencies and files named by failed checks are added as needed; tests
remain read-only except for the current suite during test generation.
"""

import json
import posixpath
import re

from infrastructure.shared.agent.files import FileWorkspace, editable_sources, source_paths
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.stages.frontend.interactions.design import api_ids
from infrastructure.utils.files import read_source

RUNTIME = "frontend/src/ui-runtime.ts"


class InteractionCheckFailure(ValueError):
    """Keep full reports for logs while exposing structured, compact repair feedback."""

    def __init__(self, message, report):
        """Attach check results so the model need not parse a duplicated report string."""
        self.feedback = {"error": message, "checks": report}
        super().__init__(f"{message}: {report}")


def model_context(context, event_ids=None):
    """Select exact event contracts and semantic UI/data; omit visual layout and fixtures.

    Requirement/test tasks retain all scenario elements and bindings. A single
    event needs its trigger sources, declared writes, and variables mentioned in
    its actions/contracts. API contracts are selected by actual event calls.
    """
    selected = set(context["events"]) if event_ids is None else set(event_ids)
    events = {eid: context["events"][eid] for eid in sorted(selected)}
    contracts = {eid: context["contracts"][eid] for eid in sorted(selected)}
    triggers = {tid: trigger for tid, trigger in context["triggers"].items() if trigger["action"] in selected}
    sources = {trigger["source"] for trigger in triggers.values()}
    mentioned = json.dumps({"events": events, "contracts": contracts}, ensure_ascii=False)
    pages = {}
    for pid, subtree in context["page_subtrees"].items():
        # A form-level trigger may describe its inputs collectively. Keep all
        # descendant data rather than requiring exact variable names in prose.
        source_elements = set(sources)
        while True:
            descendants = {uid for uid, element in subtree["elements"].items()
                if element.get("parent") in source_elements}
            if descendants.issubset(source_elements):
                break
            source_elements.update(descendants)
        bindings = subtree["bindings"]
        variables = set(bindings) if event_ids is None else {
            var for var in bindings if var in mentioned or any(
                var in element.get("data", []) for uid, element in subtree["elements"].items() if uid in source_elements)}
        elements = {uid: {**element, "prop": {key: value for key, value in element.get("prop", {}).items()
            if key not in {"style", "className"}}}
            for uid, element in subtree["elements"].items()
            if event_ids is None or uid in sources or variables.intersection(element.get("data", []))}
        pages[pid] = {**{key: value for key, value in subtree.items()
            if key in {"id", "name", "route", "root"}}, "elements": elements,
            "bindings": {var: bindings[var] for var in sorted(variables)}}
    called = {aid for event in events.values() for aid in api_ids(event)}
    result = {"page_subtrees": pages, "triggers": triggers, "events": events, "contracts": contracts,
        "target_event_ids": sorted(selected),
        "backend_apis": {aid: context["backend_apis"][aid] for aid in sorted(called)}}
    if event_ids is None:
        result["requirement"] = context["requirement"]
    return result


class InteractionFiles:
    """Select sources by semantic ownership, imports, and concrete failure feedback.

    The available-file catalogue is compiler-only. It is never sent wholesale to
    the model. All supplied application dependencies stay writable; generated
    wiring, runtime interfaces, and accepted tests stay read-only.
    """

    def __init__(self, output, ui=None):
        """Catalogue the layer once; newly created handlers are supplied explicitly."""
        self.output = output
        self.sources = set(source_paths(output, "frontend/src"))
        self.editable = set(editable_sources(output, "frontend/src"))
        self.tests = set(source_paths(output, "frontend/tests"))
        self.ui = ui or {"pages": {}, "elements": {}}

    def paths(self, kind, identities):
        """Return every selected target path, including missing indexed files for repair."""
        return {relative for identity in identities
            if (relative := selected_path(self.output, kind, identity)) is not None}

    def include(self, workspace, paths):
        """Add selected files plus transitive local imports, preserving write protection."""
        pending = list(paths)
        seen = set()
        while pending:
            relative = pending.pop()
            if relative in seen:
                continue
            seen.add(relative)
            workspace.path(relative)
            workspace.files.add(relative)
            if relative in self.editable:
                workspace.writable.add(relative)
            target = self.output / relative
            # Compiler-owned wiring can import the whole application. Supply its
            # interface only; it must not expand the source context transitively.
            if relative not in self.editable or not target.is_file():
                continue
            source = read_source(target)
            imports = re.findall(r'''(?:\bfrom\s*|\bimport\s*(?:\(\s*)?|\brequire\(\s*)["'](\.[^"']+)["']''', source)
            for imported in imports:
                base = posixpath.normpath(posixpath.join(posixpath.dirname(relative), imported))
                stem = base[:-3] if base.endswith(".js") else base[:-4] if base.endswith(".jsx") else base
                candidates = [base, *(stem + suffix for suffix in (".ts", ".tsx", ".js", ".jsx", ".json", ".css")),
                    *(base + "/index" + suffix for suffix in (".ts", ".tsx", ".js", ".jsx"))]
                found = next((path for path in candidates if path in self.sources), None)
                if found:
                    pending.append(found)

    def workspace(self, *, events=(), references=(), target=None, existing=None):
        """Include all requested handlers; a missing new target retains model-selected naming."""
        self.sources.update(source_paths(self.output, "frontend/src"))
        self.editable.update(editable_sources(self.output, "frontend/src"))
        self.tests.update(source_paths(self.output, "frontend/tests"))
        workspace = (FileWorkspace.for_target(self.output, *target, existing=existing)
            if target else FileWorkspace(self.output, ()))
        paths = self.paths("event", events)
        # New handlers may have been created since this catalogue was built.
        self.sources.update(paths)
        self.editable.update(paths)
        self.include(workspace, paths)
        workspace.files.update(references)
        workspace.files.add(RUNTIME)
        return workspace

    def feedback(self, workspace, value):
        """Expose sources/tests named in failures and compact duplicated test-report output.

        Full reports remain in compiler results/logs. The model receives failure
        details once. Successful checks and duplicate JSON `output` are omitted.
        """
        text = (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)).replace("\\\\", "/").replace("\\", "/")
        application_files = {path for path in workspace.writable if path.startswith("frontend/src/")}
        self.sources.update(application_files)
        self.editable.update(application_files)
        named = {path for path in self.sources | self.tests
            if path in text or path.removeprefix("frontend") in text}
        # UI assertion feedback often contains a locator rather than the page
        # source path. Follow that element's parents to expose the actual page.
        for uid in self.ui["elements"]:
            if uid not in text:
                continue
            current, visited = uid, set()
            while current in self.ui["elements"] and current not in visited:
                visited.add(current)
                for pid, page in self.ui["pages"].items():
                    if current == page["root"]:
                        named.update(self.paths("page", [pid]))
                current = self.ui["elements"][current].get("parent")
        for pid in self.ui["pages"]:
            if f"frontend/tests/ui/{pid}.spec.ts" in text or f"tests/ui/{pid}.spec.ts" in text:
                named.update(self.paths("page", [pid]))
        self.include(workspace, named)
        self.include(workspace, workspace.writable)

        def compact(item):
            """Remove successful checks and reporter copies without truncating actual failures."""
            if isinstance(item, dict):
                if item.get("returncode") == 0:
                    return {"returncode": 0}
                return {key: compact(child) for key, child in item.items()
                    if not (key in {"output", "stdout"} and item.get("failures"))}
            if isinstance(item, list):
                return [compact(child) for child in item]
            return item

        return compact(value)
