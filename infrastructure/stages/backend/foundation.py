"""Publish source evidence for backend design without imposing a platform schema."""

from infrastructure.utils.files import read_artifact, save_json
from infrastructure.stages.backend.evidence import compile_evidence


def design_backend_foundation(input_dir, arc_dir, pause=False, max_attempts=10):
    """Retain the stage interface; identity capabilities are designed from requirements.

    enabled=False means the former fixed platform is absent, not that source-required
    authentication/authorization is disabled. Backend agents must implement those
    capabilities using the already designed schema and the original evidence.
    """
    raw = read_artifact(arc_dir, "requirements.json")
    if not (arc_dir / "db_schema.json").is_file():
        raise ValueError("Run 02_build_db_schema before backend design")
    evidence = compile_evidence(raw, input_dir)
    save_json(arc_dir / "backend_evidence.json", evidence)
    plan = {"enabled": False, "identity_model": "source_driven",
        "implementation_notes": [{"instruction":
            "Derive identity, user types, authentication, authorization and workflows from source evidence. "
            "Implement required shared modules and real endpoints against the existing designed schema. "
            "No fixed platform tables, default accounts or identity endpoints are provided."}]}
    save_json(arc_dir / "backend_foundation.json", plan)
    return {"status": "GREEN", **plan}
