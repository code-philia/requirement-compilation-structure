"""Exercise model-edited HTTP wiring after normal compiler refreshes."""
from tool_fixtures import propose_files

import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from infrastructure.shared.agent.context import SourceFiles
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.project.initialize import initialize_project
from infrastructure.stages.backend.runtime import prepare_runtime, sync_implementations
from infrastructure.stages.frontend.triggers.runtime import sync_triggers
from infrastructure.utils.files import save_text


class ApiWiring(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('ARC_DB_TEST_NODE_MODULES'), 'Set ARC_DB_TEST_NODE_MODULES for real HTTP checks')
    def test_agent_edits_survive_refresh_and_connect_client_to_real_http_and_sqlite(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            initialize_project(output)
            (output / 'node_modules').symlink_to(Path(os.environ['ARC_DB_TEST_NODE_MODULES']).resolve())
            registry = 'backend/src/api/register.ts'
            client = 'frontend/src/ui-api.ts'
            handler = 'backend/src/books/read.ts'
            apis = {'API-READ': {'signature': {'name': 'readBook', 'method': 'GET', 'path': '/api/books/{bookId}'}}}
            prepare_runtime(output, apis)
            implementation = '''import type Database from 'better-sqlite3';
import type { ApiRequest, ApiResponse } from '../api/types.js';
export async function handle(request: ApiRequest, db: Database.Database): Promise<ApiResponse> {
  const book = db.prepare('SELECT title FROM Book WHERE id = ?').get(request.params.bookId);
  return { status: book ? 200 : 404, body: book ?? null, headers: { 'x-book-id': request.params.bookId } };
}
'''
            wiring = '''import type { Express } from 'express';
import type Database from 'better-sqlite3';
import { handle } from '../books/read.js';
export function registerApis(app: Express, db: Database.Database) {
  app.get('/api/books/:bookId', async (req, res, next) => {
    try {
      const result = await handle({ params: { bookId: String(req.params.bookId) }, query: req.query,
        body: req.body ?? {}, headers: {} }, db);
      for (const [key, value] of Object.entries(result.headers ?? {})) res.setHeader(key, value);
      res.status(result.status).json(result.body);
    } catch (error) { next(error); }
  });
}
'''
            workspace = SourceFiles(output, root='backend/src', tests_root='backend/tests').workspace(
                target=('api', 'API-READ'), paths=[registry])
            response = propose_files(output, [{'path': handler, 'content': implementation}, {'path': registry, 'content': wiring}])
            run_file_agent(Mock(generate_json=Mock(return_value=response)), '', {}, workspace,
                Mock(return_value={}), 1, Mock(), 'Backend wiring')
            ui = {'pages': {'PAGE-BOOKS': {'route': '/', 'root': 'UI-BOOKS'}}, 'elements': {}, 'bindings': {}}
            sync_triggers(output, ui, {'triggers': {}}, {'apis': apis}, [])
            client_source = '''import type { UiApiRequest, UiApiResponse } from './ui-runtime';
export async function callApi(id: string, request: UiApiRequest = {}): Promise<UiApiResponse> {
  if (id !== 'API-READ') throw new Error('Unknown API');
  const url = new URL('/api/books/' + encodeURIComponent(String(request.params?.bookId)), window.location.origin);
  const response = await fetch(url, { credentials: 'same-origin' });
  return { status: response.status, body: await response.json(), headers: Object.fromEntries(response.headers.entries()) };
}
'''
            workspace = SourceFiles(output).workspace(paths=[client])
            run_file_agent(Mock(generate_json=Mock(return_value=propose_files(output, [{'path': client, 'content': client_source}]))),
                '', {}, workspace, Mock(return_value={}), 1, Mock(), 'Frontend wiring')
            # The compiler must preserve both ends, including when preparation is repeated.
            prepare_runtime(output, apis)
            sync_implementations(output, apis)
            sync_triggers(output, ui, {'triggers': {}}, {'apis': apis}, [])
            for layer in ('backend', 'frontend'):
                compiled = subprocess.run(['node', 'node_modules/typescript/bin/tsc',
                    '-p', layer + '/tsconfig.json', '--noEmit'], cwd=output,
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            script = '''import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createApp } from './backend/src/app.ts';
import { createDatabaseClient } from './backend/src/db/client.ts';
import { callApi } from './frontend/src/ui-api.ts';
const db = createDatabaseClient(':memory:');
db.exec('CREATE TABLE Book (id TEXT PRIMARY KEY, title TEXT NOT NULL)');
const id = 'book id-123';
db.prepare('INSERT INTO Book VALUES (?, ?)').run(id, 'HTTP connected');
const server = createApp(db).listen(0, '127.0.0.1');
try {
  await once(server, 'listening');
  globalThis.window = { location: { origin: `http://127.0.0.1:${server.address().port}` } };
  const response = await callApi('API-READ', { params: { bookId: id } });
  assert.equal(response.status, 200);
  assert.deepEqual(response.body, { title: 'HTTP connected' });
  assert.equal(response.headers['x-book-id'], id);
  assert.equal((await fetch(new URL('/api/health', window.location.origin))).status, 200);
  console.log(JSON.stringify({ status: response.status, title: response.body.title }));
} finally {
  if (server.listening) await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  db.close();
}
'''
            save_text(output / 'check.mjs', script)
            result = subprocess.run(['node', '--import', 'tsx', 'check.mjs'], cwd=output,
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout), {'status': 200, 'title': 'HTTP connected'})
