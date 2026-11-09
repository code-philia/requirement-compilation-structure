"""Stage 05: lightweight API design before implementation, without detailed contracts."""

from pathlib import Path

from infrastructure.shared.agent.outlines import plan_requirements
from infrastructure.stages.backend.context import load_context, requirement_context


def design_backend_joint(arc_dir: Path, pause: bool = False) -> dict:
    """Describe API purposes, routes and suggested files; implementation owns details."""
    tree, _ = load_context(arc_dir)
    inventory = {}
    if tree.backend_foundation.get('enabled'):
        for name, method, route in (('login', 'POST', '/api/auth/login'),
                ('me', 'GET', '/api/auth/me'), ('logout', 'POST', '/api/auth/logout'),
                ('registration-options', 'GET', '/api/auth/registration-options'),
                ('register', 'POST', '/api/auth/register')):
            inventory['platform-' + name] = {
                'purpose': 'Existing platform ' + name,
                'method': method, 'path': route,
                'implementation_hint': 'backend/src/platform/runtime.ts'}
    return plan_requirements(arc_dir, 'backend', tree,
        {rid: requirement_context(tree, rid) for rid in tree.leaves},
        inventory=inventory, pause=pause)
