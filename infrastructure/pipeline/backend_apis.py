"""Stage 05: outline backend APIs, shared capabilities and their implementation locations."""

from pathlib import Path

from infrastructure.shared.agent.outlines import plan_requirements
from infrastructure.stages.backend.context import load_context, requirement_context


def design_backend_joint(arc_dir: Path, pause: bool = False) -> dict:
    """Describe APIs, shared module responsibilities/dependencies and suggested files."""
    from infrastructure.stages.backend.foundation import design_backend_foundation
    # Identity/authorization configuration belongs to backend design, not database analysis.
    design_backend_foundation(arc_dir.parent, arc_dir, pause=pause)
    tree, _ = load_context(arc_dir, validate_seeds=False)
    inventory = {}
    if tree.backend_foundation.get('enabled'):
        for name, method, route in (('login', 'POST', '/api/auth/login'),
                ('me', 'GET', '/api/auth/me'), ('logout', 'POST', '/api/auth/logout'),
                ('registration-options', 'GET', '/api/auth/registration-options'),
                ('register', 'POST', '/api/auth/register')):
            inventory['platform-' + name] = {
                'kind': 'api', 'purpose': 'Existing platform ' + name,
                'method': method, 'path': route,
                'implementation_hint': 'backend/src/platform/runtime.ts'}
    return plan_requirements(arc_dir, 'backend', tree,
        {rid: requirement_context(tree, rid) for rid in tree.leaves},
        inventory=inventory, pause=pause)
