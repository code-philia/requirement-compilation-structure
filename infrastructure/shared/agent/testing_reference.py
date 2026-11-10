"""One versioned testing guide, with role-specific excerpts injected on demand."""

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'knowledge/testing'
REFERENCE = 'references/testing/guide.md'


def testing_reference(task):
    path = task.get('test_path', '')
    if not isinstance(path, str):
        return None
    if path.startswith('backend/tests/'):
        role = 'http'
    elif path.startswith('frontend/tests/'):
        role = 'browser'
    else:
        return None
    text = (ROOT / 'guide.md').read_text(encoding='utf-8')
    sections = dict(re.findall(r'^## (\w+)\n(.*?)(?=^## |\Z)', text, flags=re.M | re.S))
    names = ['common', role, 'fixture_mechanics']
    # Auth/session and workflow conventions are shared; do not duplicate them in callers.
    foundation = task.get('backend_foundation') or task.get('requirement', {}).get('backend_foundation', {})
    if foundation.get('enabled'):
        names.append('workflow')
    return {'path': REFERENCE, 'sha256': hashlib.sha256(text.encode()).hexdigest(),
        'role': role, 'sections': {name: sections[name].strip() for name in names},
        'policy': 'Reuse these supplied APIs and examples before querying platform internals. '
                  'Read the full readonly reference only for a named missing fact. '
                  'Source requirements remain the behavioral authority.'}
