"""Human-readable names shared by single-stage and pipeline progress displays."""

from infrastructure.pipeline.stages import STAGE_DESCRIPTIONS, canonical_stage

STAGES = {name[:2]:description for name,description in STAGE_DESCRIPTIONS.items()}


def stage_label(script: str) -> str:
    """Show the pipeline stage number and its purpose."""
    script = canonical_stage(script)
    if script in STAGE_DESCRIPTIONS:
        return f"Stage {script[:2]} | {STAGE_DESCRIPTIONS[script]}"
    number = script[:2]
    return f"Stage {number} | {STAGES[number]}" if number in STAGES else script
