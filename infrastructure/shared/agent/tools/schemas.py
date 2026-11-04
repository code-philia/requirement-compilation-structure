"""Shared tool definitions, parameter schemas and execution effects."""

from .files import edit_file, read_file


def definition(name, description, properties, required, example):
    return {"tool": name, "description": description,
        "parameters": {"type": "object",
            "properties": {"tool": {"type": "string", "enum": [name]}, **properties},
            "required": ["tool", *required], "additionalProperties": False},
        "example": example}


STRING = {"type": "string"}
TOOL_REGISTRY = {
    "read_file": (read_file, definition("read_file", "Read an additional project file or inclusive 1-based line range ONLY when the current requirement "
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

