"""Human-readable names shared by single-stage and pipeline progress displays."""

STAGES = {
    "00": "Initialize project",
    "01": "Read requirements and analyze reference images",
    "02": "Design database schema",
    "03": "Infer database read/write obligations",
    "04": "Review database obligations",
    "05": "Implement database",
    "06": "Design backend APIs including P/Q",
    "07": "Review backend APIs",
    "08": "Implement backend with test-first acceptance",
    "09": "Design UI and frontend data",
    "10": "Implement UI and run existence tests",
    "11": "Design frontend triggers",
    "12": "Implement triggers and run end-to-end tests",
}


def stage_label(script: str) -> str:
    """Include the real stage number, even when optional stages are skipped."""
    number = script[:2]
    return f"Stage {number} | {STAGES[number]}" if number in STAGES else script
