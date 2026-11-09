# Shared application testing reference

## common

Original requirements and source scenarios define expected business behavior. Actual
routes and endpoint usage define transport, never expected outcomes. Use source test
accounts supplied in task.test_accounts; never copy example credentials into production.
Fixtures restore explicit SEED records. Arrange only minimal isolated Given state, with
real FK parents, 0/1 booleans and exact decimal text. CREATED/DERIVED records must result
from the actual When operation. Do not depend on another test's rows or execution order.
The host owns temporary databases, server ports, lifecycle, compilation and acceptance.
Do not initialize/reset a fixture again, open another DB/server, mock requests, call a
handler directly, or install dependencies. Keep each actor's session separate.
These examples describe compiler-owned helper APIs, not new business requirements.

## http

Use the login example only when the platform is enabled or these actual auth endpoints
exist. Otherwise follow the source-required authentication transport.
Import node:test and node:assert/strict. A suite under backend/tests/requirements uses:

```ts
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createApiTest, fixturePasswordHash } from '../support/context.js';

test('SOURCE-SCENARIO-ID source behavior', async t => {
  const { database, baseURL } = createApiTest(t);
  // Substitute a source account from task.test_accounts.
  const login = await fetch(new URL('/api/auth/login', baseURL), {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ username: 'SOURCE_USERNAME', password: 'SOURCE_PASSWORD' }),
    redirect: 'manual'
  });
  assert.equal(login.status, 200);
  const { csrfToken } = await login.json() as { csrfToken: string };
  const cookie = login.headers.getSetCookie().map(v => v.split(';')[0]).join('; ');
  const headers = { Cookie: cookie, 'X-CSRF-Token': csrfToken,
    'content-type': 'application/json' };
  // Use headers with the actual source-required mutation route/body.
  // Given: database.prepare('...').run(...); When: real fetch; Then: response + SQL.
});
```

createApiTest(t) returns {database, baseURL}, resets startup rows in its owned temporary
DB and closes the connection after the test. fixturePasswordHash(password) returns a
compatible scrypt encoding only for isolated Given accounts. Fetch has no cookie jar:
forward Cookie explicitly; track refreshed cookie/CSRF responses. Never forge identity
headers. For 204 skip JSON parsing. Read the supplied helper if its API changes, not the
whole platform runtime or every previous suite. Tests execute sequentially.

## browser

The fixed login/session conventions below apply to the enabled platform; otherwise use
the actual source-defined login behavior.
Import the real browser fixture; never import @playwright/test's test directly:

```ts
import { test, expect } from './support/context.js';

test('SOURCE-SCENARIO-ID visible behavior', async ({ page, database }) => {
  // Arrange source-required Given rows with database.prepare(...), not production seeds.
  // Navigate to the actual application login route, then fill visible username/password
  // fields using their source-required accessible labels and a task.test_accounts account.
  // Click the real login button and await an authenticated page or /api/auth/me response.
  // Drive When through actual UI controls. Assert visible Then and persisted results.
});
```

Adjust the relative support import to task.test_path. The auto database fixture resets
SEED rows before each case and exposes the same DB used by the real backend. The page
browser context manages HttpOnly cookies; never set browser Cookie headers manually.
For Given-only API setup when login itself is not the scenario's When operation:

```ts
const login = await page.request.post('/api/auth/login', {
  data: { username: 'SOURCE_USERNAME', password: 'SOURCE_PASSWORD' }
});
expect(login.status()).toBe(200);
const session = await login.json();
// page.request shares this browser context's cookie jar.
// A Given mutation uses headers: { 'X-CSRF-Token': session.csrfToken }.
// Use a separate browser context and its own token for a second actor.
```

The normal fixture uses same-origin Vite /api proxying; preserve that host/origin setup.
A page.request response is APIResponse; page.waitForResponse returns Response. A helper
supporting both Page and Locator must accept Page | Locator. Arco Select uses real popup
options, not native selectOption; locate the visible combobox by accessible label, click,
then select the source option from the visible popup. Dialog labels and row identity
come from the source. For a download, drive the actual UI and inspect its contents.
Do not read platform internals to rediscover cookies or fixture initialization unless
specific runtime evidence contradicts these documented APIs.

## workflow

Account/password login, opaque session cookies and csrfToken come from the fixed
/api/auth/login and /api/auth/me endpoints; /api/auth/logout invalidates the session.
Use the latest cookie/token after login or refresh. Mutations need X-CSRF-Token.
Workflow and bulk commands also require Idempotency-Key: retain one key and identical
payload for retries/replay of the same intent; use a new key for a different intent.
The businessRoute gateway owns transactions, permission/organization checks, workflow
state changes, audit and receipts. A successful command commits real effects; rejection
must leave business rows unchanged. Assert source-defined guards, effects, replay,
isolation and reversal behavior where required. Never update canonical machine state to
simulate the When action, manufacture sessions or bypass authorization with role headers.
Default admin has full permissions; ordinary accounts have source-defined permissions.
Exact resource/action/machine IDs and additional policy come from the supplied source
and foundation, not these examples. Infrastructure tables may be used for isolated Given
setup only when the original scenario requires it; do not fabricate extra memberships.
