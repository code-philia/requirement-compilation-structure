"""Human-readable names shared by single-stage and pipeline progress displays."""

from infrastructure.pipeline.stages import STAGE_DESCRIPTIONS, canonical_stage

# Short numbers are accepted only for legacy internal log calls.
LEGACY_NUMBERS = {'00':'project_initialization', '01':'read_requirements',
    '02':'build_db_schema', '03':'correct_db', '04':'implement_db',
    '05':'build_backend', '06':'build_frontend'}


def stage_label(script: str) -> str:
    name = canonical_stage(LEGACY_NUMBERS.get(script, script))
    if name in STAGE_DESCRIPTIONS:
        return f"{name} | {STAGE_DESCRIPTIONS[name]}"
    return script
