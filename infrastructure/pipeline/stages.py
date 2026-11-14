"""Execution-ordered stages, historical CLI aliases and equivalent checkpoints."""

STAGE_DESCRIPTIONS = {
    'project_initialization': 'Initialize project',
    'read_requirements': 'Read requirements and analyze referenced images',
    'build_database': 'Design the complete database from ER and all requirements, implement DDL and startup data',
    'build_backend': 'Design APIs/modules, implement and repair compilation without generated self-tests',
    'build_frontend': 'Design UI/components, implement and accept using supplied requirement tests',
}

STAGE_SHORT_NAMES = dict(zip(STAGE_DESCRIPTIONS,
    ('Init', 'Requirements', 'Database', 'Backend', 'Frontend')))

# Names remain accepted at the CLI; only the names above are published in new reports.
STAGE_ALIASES = {
    '00_project_initialization': 'project_initialization',
    '01_explore_requirement': 'read_requirements',
    'build_db_schema': 'build_database',
    'implement_db': 'build_database',
    'correct_db': 'build_database',
    '02_build_db_schema': 'build_database',
    '03_infer_db_obligations': 'build_database',
    'analyze_db_requirements': 'build_database',
    '04_implement_db': 'build_database',
    '05_build_backend': 'build_backend',
    '06_build_frontend': 'build_frontend',
    '02_design_backend_foundation': 'build_backend',
    '05_design_backend_joint': 'build_backend',
    '05_design_backend_apis': 'build_backend',
    '06_implement_backend_tdd': 'build_backend',
    '07_build_frontend': 'build_frontend',
    '07_design_frontend_joint': 'build_frontend',
    '07_design_ui': 'build_frontend',
    '08_implement_ui': 'build_frontend',
    '09_design_frontend_triggers': 'build_frontend',
    '10_implement_frontend_joint': 'build_frontend',
    '10_implement_frontend_tdd': 'build_frontend',
}

# Design-only historical checkpoints cannot stand in for completed implementation.
CHECKPOINT_NAMES = {
    'project_initialization': ('project_initialization', '00_project_initialization'),
    'read_requirements': ('read_requirements', '01_explore_requirement'),
    'build_database': ('build_database', 'correct_db'),
    'build_backend': ('build_backend', '05_build_backend', '06_implement_backend_tdd'),
    'build_frontend': ('build_frontend', '06_build_frontend', '07_build_frontend',
        '10_implement_frontend_joint', '10_implement_frontend_tdd'),
}


def canonical_stage(name):
    return STAGE_ALIASES.get(name, name)
