"""Canonical stage names, historical CLI aliases and equivalent checkpoints."""

STAGE_DESCRIPTIONS = {
    '00_project_initialization': 'Initialize project',
    '01_explore_requirement': 'Read requirements and analyze reference images',
    '02_build_db_schema': 'Build logical schema from ER with native tools',
    '03_infer_db_obligations': 'Refine schema and derive requirement read/write obligations',
    '04_implement_db': 'Implement database and startup data',
    '05_build_backend': 'Design APIs/modules, generate tests and implement backend requirements',
    '06_build_frontend': 'Design UI/components, generate tests and implement frontend requirements',
}

STAGE_SHORT_NAMES = {
    '00': 'Init', '01': 'Requirements', '02': 'Schema', '03': 'R/W',
    '04': 'Database', '05': 'Backend', '06': 'Frontend',
}

# Selecting a former substage now runs its whole merged replacement.
STAGE_ALIASES = {
    '02_design_backend_foundation': '05_build_backend',
    '05_design_backend_joint': '05_build_backend',
    '05_design_backend_apis': '05_build_backend',
    '06_implement_backend_tdd': '05_build_backend',
    '07_build_frontend': '06_build_frontend',
    '07_design_frontend_joint': '06_build_frontend',
    '07_design_ui': '06_build_frontend',
    '08_implement_ui': '06_build_frontend',
    '09_design_frontend_triggers': '06_build_frontend',
    '10_implement_frontend_joint': '06_build_frontend',
    '10_implement_frontend_tdd': '06_build_frontend',
}

# Only completed implementation checkpoints are equivalent. A successful former
# design-only pass must never substitute for a completed backend/frontend build.
CHECKPOINT_NAMES = {
    '05_build_backend': ('05_build_backend', '06_implement_backend_tdd'),
    '06_build_frontend': ('06_build_frontend', '07_build_frontend',
        '10_implement_frontend_joint', '10_implement_frontend_tdd'),
}


def canonical_stage(name):
    return STAGE_ALIASES.get(name, name)
