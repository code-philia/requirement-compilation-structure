"""Unrelated requirements and sources must not inflate a local task."""
import tempfile
import unittest
from pathlib import Path
from infrastructure.shared.agent.context import SourceFiles
from infrastructure.stages.backend.context import requirement_context, related_schema
from infrastructure.stages.requirements.tree import RequirementTree


class BoundedContext(unittest.TestCase):
    def test_unrelated_growth_keeps_local_input_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'frontend/src').mkdir(parents=True)
            (root / 'frontend/src/current.ts').write_text('export const current = 1;')
            request = {'id': 'REQ', 'description': 'Current task'}
            schema = {'entities': {'Account': {'fields': {'id': {}}}}}
            def context():
                return (requirement_context(RequirementTree(request), 'REQ'),
                    related_schema(schema, [{'read': ['Account.id'], 'write': []}]),
                    SourceFiles(root).workspace(paths=['frontend/src/current.ts']).state())
            initial = context()
            request['children'] = [{'id': f'OTHER-{i}'} for i in range(100)]
            for i in range(100):
                schema['entities'][f'Other{i}'] = {'fields': {'id': {}}}
                (root / f'frontend/src/other{i}.ts').write_text('unrelated')
            self.assertEqual(initial, context())
