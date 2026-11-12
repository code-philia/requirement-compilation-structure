"""Human-readable names shared by single-stage and pipeline progress displays."""

STAGES = {
    "00": "Initialize project",
    "01": "Read requirements and analyze reference images",
    "02": "Design database schema",
    "03": "Infer database read/write obligations",
    "04": "Implement database",
    "05": "Design backend APIs including P/Q",
    "06": "Implement designed APIs and verify behavior",
    "07": "Design UI and frontend data",
    "08": "Implement UI and run existence tests",
    "09": "Design frontend triggers",
    "10": "Implement triggers and run end-to-end tests",
}


def stage_label(script: str) -> str:
    """Show the pipeline stage number and its purpose."""
    joint = {
        "05_build_backend": "Design and implement APIs/modules per requirement with hybrid retrieval",
        "02_build_db_schema": "Build logical schema from ER with native tools",
        "03_infer_db_obligations": "Refine schema and derive requirement read/write obligations",
        "05_design_backend_joint": "Outline backend APIs, shared modules and implementation locations",
        "07_design_frontend_joint": "Outline pages and implementation locations",
        "10_implement_frontend_joint": "Implement pages and interactions directly from source evidence",
    }
    if script in joint:
        return f"Stage {script[:2]} | {joint[script]}"
    number = script[:2]
    return f"Stage {number} | {STAGES[number]}" if number in STAGES else script
