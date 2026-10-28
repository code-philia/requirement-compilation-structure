"""Resolve the requirement tree, database symbols, and checked obligations."""

from pathlib import Path

from infrastructure.utils.files import read_artifact

from infrastructure.stages.database.obligations.records import field_symbols, validate_obligations
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.database.schema import validate_schema


def load_context(arc_dir: Path):
    """Load the requirement tree, validated schema, checked obligations, and unresolved coverage TODOs."""
    tree = RequirementTree(read_artifact(arc_dir, "requirements.json"))
    schema = read_artifact(arc_dir, "db_schema.json")
    validate_schema(schema)
    checked = read_artifact(arc_dir, "db_obligations_checked.json")
    if not isinstance(checked, dict) or set(checked) != {"requirements", "steps", "todos"}:
        raise ValueError("Expected checked obligations with requirements, steps, and todos")
    obligations = validate_obligations({key: checked[key] for key in ("requirements", "steps")}, tree, field_symbols(schema))
    return tree, schema, obligations, checked["todos"]


def requirement_context(tree, rid: str) -> dict:
    """Return one requirement with its own structured steps and their concatenated teaching/model context."""
    return {**tree.requirements[rid], "steps": [tree.steps[sid] for sid in tree.own_steps[rid]], "concatenated_steps": tree.concatenated_steps(rid)}


def supplied_sources(output: Path, api: dict, schema: dict) -> dict:
    """The caller selects context paths; the agent never explores the codebase."""
    entities = {symbol.split(".")[0] for mode in ("read", "write") for symbol in api[mode]}
    pending = list(entities)
    while pending:
        name = pending.pop()
        for field in schema["entities"][name]["fields"].values():
            if field["references"]:
                target = field["references"].split(".")[0]
                if target not in entities:
                    entities.add(target)
                    pending.append(target)
    paths = ["backend/src/api/types.ts", "backend/src/db/client.ts", "backend/src/db/initialize.ts", "backend/tests/support/context.ts"]
    paths.extend(f"backend/src/db/tables/{name}.sql" for name in sorted(entities))
    return {relative: (output / relative).read_text(encoding="utf-8") for relative in paths}
