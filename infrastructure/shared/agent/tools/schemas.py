"""Shared tool definitions, parameter schemas and execution effects."""

from .files import edit_file, read_file
from .search import list_files, search_files
from infrastructure.shared.agent.repairs import request_design_revision, TARGETS


def definition(name, description, properties, required, example):
    return {"tool": name, "description": description,
        "parameters": {"type": "object",
            "properties": {"tool": {"type": "string", "enum": [name]}, **properties},
            "required": ["tool", *required], "additionalProperties": False},
        "example": example}


STRING = {"type": "string"}
TOOL_REGISTRY = {
    "request_design_revision": (request_design_revision, definition("request_design_revision",
        "Request a source-backed upstream contract/compiler correction instead of editing protected artifacts or weakening tests. Pauses this task and records impacted stages for review/recompilation.",
        {"target":{"type":"string","enum":list(TARGETS)},"requirements":{"type":"array","items":STRING},
            "source_refs":{"type":"array","items":STRING},"reason":STRING,"proposed_change":STRING,
            "issue_code":{"type":"string","enum":["other","missing_scoped_read"]}},
        ["target","requirements","source_refs","reason","proposed_change"],
        {"tool":"request_design_revision","target":"backend_api","requirements":["REQ-example"],"source_refs":["STEP-example-01-01"],"reason":"Source requires an omitted transactional effect","proposed_change":"Add the source-required ledger write to canonical API obligations and P/Q"}), "control"),
    "list_files": (list_files, definition("list_files", "Find authorized project/reference files by POSIX glob. ** matches zero or more directories. Readonly; use next_offset to page results.",
        {"glob":STRING,"offset":{"type":"integer","minimum":0},"limit":{"type":"integer","minimum":1}}, [],
        {"tool":"list_files","glob":"references/arco/api/**/Table/**/*.d.ts","limit":20}), "read"),
    "search_files": (search_files, definition("search_files", "Case-insensitive literal text search in authorized files, filtered by glob. Returns paths, 1-based line numbers and bounded context. No regex or shell. Narrow glob if scan_truncated; read_file for complete definitions.",
        {"query":STRING,"glob":STRING,"offset":{"type":"integer","minimum":0},"limit":{"type":"integer","minimum":1},"context":{"type":"integer","minimum":0}}, ["query"],
        {"tool":"search_files","query":"onChange","glob":"references/arco/api/**/Select/**/*.d.ts","limit":10,"context":2}), "read"),
    "read_file": (read_file, definition("read_file", "Read an authorized project file or readonly compiler reference, with an optional inclusive 1-based line range, ONLY when the current requirement "
        "cannot be completed correctly using the full related-file contents already in input.files. "
        "Explain the concrete missing dependency in diagnosis.reason. Do not re-read supplied or retained files.",
        {"path": STRING, "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1}}, ["path"],
        {"tool": "read_file", "path": "backend/src/db/initialize.ts", "start_line": 1, "end_line": 40}), "read"),
    "edit_file": (edit_file, definition("edit_file", "Create a new file, replace one unique exact text span, "
        "or prepend/append to an existing file. Paths are relative to the project working directory. "
        "replace needs a local old_content span copied from supplied/read source. "
        "Never replace a whole existing file; preserve all earlier requirements and extend shared code incrementally.",
        {"path": STRING, "operation": {"type": "string", "enum": ["create", "replace", "prepend", "append"]},
            "old_content": STRING, "new_content": STRING}, ["path", "operation", "new_content"],
        {"tool": "edit_file", "path": "backend/src/example.ts", "operation": "replace",
            "old_content": "exact existing span", "new_content": "replacement span"}), "write"),
}

