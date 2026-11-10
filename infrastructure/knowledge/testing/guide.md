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

Use the compiler-owned backend/tests/support/context.ts, which reexports fixed helpers:
createApiTest(t), fixturePasswordHash(password), loginSession(baseURL,account),
sessionRequest(session,path,options), insertGiven(db,table,values), ownGiven(db,ownership)
findGiven(db,table,locator), ensureGiven(db,table,uniqueLocator,values),
sessionIdentity(session), readResponse(response) and prepareGiven(callback). Do not regenerate these helper implementations in each suite.

```ts
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createApiTest, loginSession, sessionRequest, prepareGiven,
  insertGiven, ownGiven, findGiven, ensureGiven, sessionIdentity, readResponse } from '../support/context.js';
test('SOURCE-SCENARIO-ID source behavior', async t => {
  const {database, baseURL} = createApiTest(t);
  const given = await prepareGiven(async () => {
    // Source-specific values/real FK parents belong here. insertGiven generates a
    // missing technical TEXT id only; it never guesses statuses, names or ownership.
    return {};
  });
  // Substitute an actual task.test_accounts account. Use normal fetch when login
  // itself is the When action or a rejection response must be observed.
  const session = await loginSession(baseURL, {username:'SOURCE_USERNAME',password:'SOURCE_PASSWORD'});
  const identity = await sessionIdentity(session); // actual persisted IDs, not catalog codes
  const response = await sessionRequest(session, '/SOURCE_ROUTE', {method:'GET'});
  const result = await readResponse(response); // {status, body, text, headers}; cached per Response
  // Assert result.status/body and source-required database effects. Never consume the raw body again.
  // Assert the original Then, including relevant database observations.
});
```

sessionRequest accepts {method,body,idempotencyKey,headers}, manages Cookie and CSRF,
updates refreshed cookies/tokens and returns the raw fetch Response. It never turns an
error status into success; assert source-required statuses and effects. Use separate
sessions per actor. Login helper expects success and is only Given setup. For 204 skip
JSON parsing. The fixture owns resets, cleanup and the temporary server/database.

## browser

Import test/expect and shared helpers from frontend/tests/e2e/support/context.ts;
never import @playwright/test's test directly. Adjust the relative path to test_path.

```ts
import {test,expect,prepareGiven,insertGiven,ownGiven,
  loginGiven,browserRequest} from './support/context.js';
test('SOURCE-SCENARIO-ID visible behavior', async ({page,database}) => {
  const given = await prepareGiven(async () => {
    // Insert all isolated source Given rows, FK parents and ownership here.
    return {};
  });
  // If login is Given only, loginGiven(page, sourceAccount) uses page.request's
  // cookie jar. If login is the scenario When, use the actual login UI instead.
  // All business When actions go through real UI; assert visible Then + persistence.
});
```

loginGiven returns {request,csrfToken}. browserIdentity(session) obtains actual persisted
user/unit IDs from the fixed /api/auth/me endpoint when that platform is enabled. browserRequest(session,path,{method,data,
idempotencyKey,headers}) performs Given-only API setup with current CSRF and browser
cookies and returns APIResponse. UI When must not be replaced by this helper. Use a
separate browser context/token per actor. HttpOnly cookies are browser-managed.
prepareGiven marks only isolated data preparation failures with ARC_FIXTURE_SETUP;
never put real When/Then or network/environment failures inside it. The DB fixture
resets SEED data per test: earlier tests never leave records for a later test. Do not
modify production startup seed to manufacture Given data.

insertGiven(db,table,values) uses parameterized SQL and validates actual columns;
ownGiven(db,{resource,recordId,unitId,ownerId?,assigneeId?}) inserts isolated ownership.
These do not invent business values, permissions or memberships. Supply real source
fields/FK parents. No domain-specific warehouse/product data is hardcoded in templates.
A page.request result is APIResponse; waitForResponse returns Response. Shared scope
helpers may accept Page | Locator. Arco Select uses popup options rather than native
selectOption. Drive actual downloads and inspect contents. Fixed platform endpoints
apply only when enabled; otherwise use the actual source authentication transport.

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

## fixture_mechanics

createApiTest already restores source SEED records and fixed platform accounts/memberships.
Do not insert these rows again blindly. findGiven(db,table,locator) looks up one explicit
row and rejects ambiguous matches. ensureGiven accepts only an actual non-null PK/UNIQUE
locator and explicit source values: it reuses a matching row, inserts an absent row,
and rejects mismatched values. It never updates existing data, ignores uniqueness
errors, invents business values or prepares the When outcome. Use insertGiven when
an explicitly new Given record is required. Reusing startup SEED and testing creation
of a new business record are different source scenarios; choose values accordingly.
For fixed authentication, sessionIdentity(session) resolves the current persisted user
and unit IDs from /api/auth/me. Catalog codes are not necessarily database primary keys.
Additional actors/teams/roles require explicit source-authorized isolated Given data;
never manufacture memberships or remove seed data just to pass a test.
readResponse(response) consumes a fetch body once and caches {status,body,text,headers}.
Use this object for assertions and failure messages. Never use assert.equal(r.status,
expected,await r.text()) then r.json(): assertion-message arguments run even on success.
Browser APIResponse is already reusable; findGiven/ensureGiven are reexported for browser
Given setup. All helpers are domain-independent and operate on actual schema/records.
