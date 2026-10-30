"""Supply task sources and local imports; expand repair context from concrete failures."""

import json
import posixpath
import re

from infrastructure.shared.agent.files import FileWorkspace, editable_sources, source_paths
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.utils.files import read_source


class SourceFiles:
    """Select sources by semantic ownership, imports, and concrete failure feedback.

    The available-file catalogue is compiler-only. It is never sent wholesale to
    the model. All supplied application dependencies stay writable; generated
    wiring, runtime interfaces, and accepted tests stay read-only.
    """

    def __init__(self, output, ui=None, *, root="frontend/src", tests_root="frontend/tests"):
        """Catalogue the layer once; newly created handlers are supplied explicitly."""
        self.output, self.root, self.tests_root = output, root, tests_root
        self.layer = root.split("/", 1)[0]
        self.sources = set(source_paths(output, root))
        self.editable = set(editable_sources(output, root))
        self.tests = set(source_paths(output, tests_root))
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

    def workspace(self, *, triggers=(), references=(), target=None, existing=None, paths=()):
        """Include all requested handlers; a missing new target retains model-selected naming."""
        self.sources.update(source_paths(self.output, self.root))
        self.editable.update(editable_sources(self.output, self.root))
        self.tests.update(source_paths(self.output, self.tests_root))
        workspace = (FileWorkspace.for_target(self.output, *target, existing=existing)
            if target else FileWorkspace(self.output, ()))
        paths = set(paths) | self.paths("trigger", triggers)
        paths.update(workspace.writable)
        # New handlers may have been created since this catalogue was built.
        self.sources.update(paths)
        self.editable.update(path for path in paths if path.startswith(self.root + "/"))
        self.include(workspace, paths)
        workspace.files.update(references)
        return workspace

    def feedback(self, workspace, value):
        """Expose sources/tests named in failures and compact duplicated test-report output.

        Full reports remain in compiler results/logs. The model receives failure
        details once. Successful checks and duplicate JSON `output` are omitted.
        """
        text = (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)).replace("\\\\", "/").replace("\\", "/")
        application_files = {path for path in workspace.writable if path.startswith(self.root + "/")}
        self.sources.update(application_files)
        self.editable.update(application_files)
        named = {path for path in self.sources | self.tests
            if path in text or path.removeprefix(self.layer + "/") in text}
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
