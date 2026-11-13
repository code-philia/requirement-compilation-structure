"""Human-readable names shared by single-stage and pipeline progress displays."""

from infrastructure.pipeline.stages import STAGE_DESCRIPTIONS, canonical_stage

# Short numbers are accepted only for legacy internal log calls.
LEGACY_NUMBERS = dict(zip(('00','01','02','03','04','05','06'), STAGE_DESCRIPTIONS))


def stage_label(script: str) -> str:
    name = canonical_stage(LEGACY_NUMBERS.get(script, script))
    if name in STAGE_DESCRIPTIONS:
        return f"{name} | {STAGE_DESCRIPTIONS[name]}"
    return script
