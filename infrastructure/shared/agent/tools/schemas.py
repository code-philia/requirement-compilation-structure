"""Shared tool definitions, parameter schemas and execution effects."""

from .files import edit_file, read_file


def definition(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}}}


STRING = {"type": "string"}
TOOL_REGISTRY = {
    "read_file": (read_file, definition("read_file", "Read a relevant project file or inclusive 1-based line range. "
        "Prefer supplied files; read only missing evidence needed for this task.",
        {"path": STRING, "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1}}, ["path"]), "read"),
    "edit_file": (edit_file, definition("edit_file", "Create a new file, replace one unique exact text span, "
        "or prepend/append to an existing file. Paths are relative to the project working directory. "
        "replace needs a local old_content span copied from supplied/read source. "
        "Never replace a whole existing file; preserve all earlier requirements and extend shared code incrementally.",
        {"path": STRING, "operation": {"type": "string", "enum": ["create", "replace", "prepend", "append"]},
            "old_content": STRING, "new_content": STRING}, ["path", "operation", "new_content"]), "write"),
}

