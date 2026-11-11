"""Generate prerequisite SQL and execute fixed database initialization checks."""

from infrastructure.shared.agent.feedback import CheckFailure
from infrastructure.shared.agent.tools.file_tools import NativeFileTools
from infrastructure.stages.database.implementation_agent import DatabaseImplementationAgent
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.shared.project.git import checkpoint
from infrastructure.stages.database.order import table_dependencies, implementation_groups
from infrastructure.stages.database.testing import DatabaseChecks
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.backend.context import requirement_context
from infrastructure.utils.files import read_artifact, save_json, save_text
from infrastructure.stages.database.runtime import seed_source


SEED_PATH = "backend/src/db/seed.ts"


def implement_startup_data(arc_dir, schema, console, failures):
    """Create per-table files, then accumulate prerequisite rows one requirement at a time."""
    output = arc_dir.parent.resolve()
    order = [name for group in implementation_groups(schema) for name in group]
    insert_paths = {name: f"backend/src/db/seeds/{name}.sql" for name in order}
    for name, relative in insert_paths.items():
        if not (output / relative).is_file():
            save_text(output / relative, f"-- Prerequisite rows for {name}; extended incrementally by requirement.\n")
    save_text(output / SEED_PATH, seed_source(order))
    checkpoint(output, stage="04", task="startup data loader", action="Publish per-table insertion files and loader",
        details={"insertion_order": order, "insert_files": insert_paths})

    tree = RequirementTree(read_artifact(arc_dir, "requirements.json"))
    dependencies = table_dependencies(schema)
    allowed = set(insert_paths.values())
    readable = allowed | {f"backend/src/db/tables/{name}.sql" for name in order}
    for rid in tree.leaves:
        requirement = requirement_context(tree, rid)
        if not requirement["description"] and not requirement["steps"]:
            continue
        with failures.task("startup data / " + rid):
            names = set()
            for symbol in schema["requirements"].get(rid, []):
                names.add(symbol.split(".", 1)[0])
            pending = list(names)
            while pending:
                for parent in dependencies[pending.pop()]:
                    if parent not in names:
                        names.add(parent)
                        pending.append(parent)
            entities = {name: schema["entities"][name] for name in sorted(names)}
            files = NativeFileTools(output, requirements=[rid], stage="database",
                writable=allowed, readable=readable)
            task = {"requirement": requirement, "entities": entities, "table_names": order,
                "insert_files": {name: insert_paths[name] for name in sorted(names)}}

            agent = DatabaseImplementationAgent("seed")
            try:
                result = agent.run(task, files)
            finally:
                agent.model.client.close()
            checkpoint(output, stage="04", task=rid, action="Publish prerequisite insertion SQL",
                details=result)


def verify_database_runtime(arc_dir, schema, console):
    """Execute the fixed build/initialization/startup checks without an agent repair loop."""
    output = arc_dir.parent.resolve()
    report = {"status": "CHECKING", "expected_tables": list(schema["entities"])}
    path = arc_dir / "db_checks.json"
    save_json(path, report)
    try:
        install_dependencies(output)
        result = DatabaseChecks(output, schema).run()
        report.update(status="GREEN" if result["returncode"] == 0 else "FAILED", checks=result)
        save_json(path, report)
        checkpoint(output, stage="04", task="database runtime", action="Execute fixed database initialization and startup checks",
            status=report["status"], details=result)
        if result["returncode"]:
            raise CheckFailure("Database initialization or startup failed", result)
        return report
    except Exception as error:
        report.update(status="FAILED", error=str(error))
        save_json(path, report)
        raise
