"""Execution-ordered stages, historical CLI aliases and equivalent checkpoints."""

STAGE_DESCRIPTIONS = {
    'project_initialization': 'Initialize project',
    'read_requirements': 'Read requirements and analyze referenced images',
    'build_db_schema': 'Build initial logical schema from ER and explicit data',
    'analyze_db_requirements': 'Analyze requirement batches: repair schema, collect presets and derive obligations',
    'implement_db': 'Implement DDL, insert startup data and repair initialization',
    'build_backend': 'Design APIs/modules, generate tests and implement backend requirements',
    'build_frontend': 'Design UI/components, implement and accept using supplied requirement tests',
}

STAGE_SHORT_NAMES = dict(zip(STAGE_DESCRIPTIONS,
    ('Init', 'Requirements', 'Schema', 'DB analysis', 'Database', 'Backend', 'Frontend')))

# Names remain accepted at the CLI; only the names above are published in new reports.
STAGE_ALIASES = {
    '00_project_initialization': 'project_initialization',
    '01_explore_requirement': 'read_requirements',
    '02_build_db_schema': 'build_db_schema',
    '03_infer_db_obligations': 'analyze_db_requirements',
    '04_implement_db': 'implement_db',
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
    'build_db_schema': ('build_db_schema', '02_build_db_schema'),
    'analyze_db_requirements': ('analyze_db_requirements', '03_infer_db_obligations'),
    'implement_db': ('implement_db', '04_implement_db'),
    'build_backend': ('build_backend', '05_build_backend', '06_implement_backend_tdd'),
    'build_frontend': ('build_frontend', '06_build_frontend', '07_build_frontend',
        '10_implement_frontend_joint', '10_implement_frontend_tdd'),
}


def canonical_stage(name):
    return STAGE_ALIASES.get(name, name)
