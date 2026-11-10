// Compiler-owned helpers. Expected business values always come from source requirements.
import type Database from 'better-sqlite3';
import { randomUUID } from 'node:crypto';

export interface TestAccount { username: string; password: string; unit?: string }
export interface HttpSession { baseURL: string; cookie: string; csrfToken: string }
const ident = (name: string) => {
  if (!name || name.includes('\0')) throw new Error('Invalid fixture identifier');
  return '"' + name.replaceAll('"', '""') + '"';
};
export async function loginSession(baseURL: string, account: TestAccount): Promise<HttpSession> {
  const response = await fetch(new URL('/api/auth/login', baseURL), {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify(account), redirect: 'manual'
  });
  if (response.status !== 200) throw new Error(`Fixture login failed: ${response.status} ${await response.text()}`);
  const body = await response.json() as { csrfToken: string };
  return { baseURL, csrfToken: body.csrfToken,
    cookie: response.headers.getSetCookie().map(v => v.split(';')[0]).join('; ') };
}
export async function sessionRequest(session: HttpSession, path: string,
    options: {method?: string; body?: unknown; idempotencyKey?: string; headers?: Record<string,string>} = {}) {
  const headers: Record<string,string> = { Cookie: session.cookie,
    'X-CSRF-Token': session.csrfToken, ...options.headers };
  if (options.body !== undefined) headers['content-type'] = 'application/json';
  if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey;
  const response = await fetch(new URL(path, session.baseURL), { method: options.method ?? 'GET', headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body), redirect: 'manual' });
  const cookies = response.headers.getSetCookie();
  if (cookies.length) {
    const jar = new Map(session.cookie.split('; ').filter(Boolean).map(v => [v.split('=')[0], v]));
    for (const value of cookies) { const item = value.split(';')[0]; jar.set(item.split('=')[0], item); }
    session.cookie = [...jar.values()].join('; ');
  }
  if (response.ok && response.headers.get('content-type')?.includes('application/json')) {
    const body = await response.clone().json() as {csrfToken?: string};
    if (body.csrfToken) session.csrfToken = body.csrfToken;
  }
  return response; // Raw response: callers must assert statuses and source outcomes.
}
function insertRow(database: Database.Database, table: string, values: Record<string,unknown>) {
  const fields = database.prepare(`PRAGMA table_info(${ident(table)})`).all() as {name:string;pk:number;type:string}[];
  if (!fields.length) throw new Error('Unknown fixture table: ' + table);
  const row = { ...values };
  if (fields.filter(f => f.pk).length === 1 && fields.some(f => f.name === 'id' && f.pk && f.type.toUpperCase() === 'TEXT') && row.id === undefined)
    row.id = randomUUID();
  const keys = Object.keys(row);
  if (keys.some(k => !fields.some(f => f.name === k))) throw new Error('Unknown fixture column');
  const bind = keys.map(k => typeof row[k] === 'boolean' ? Number(row[k]) : row[k]);
  const result = keys.length ? database.prepare(`INSERT INTO ${ident(table)} (${keys.map(ident).join(',')}) VALUES (${keys.map(() => '?').join(',')})`).run(...bind)
    : database.prepare(`INSERT INTO ${ident(table)} DEFAULT VALUES`).run();
  if (row.id === undefined && fields.some(f => f.name === 'id' && f.pk)) row.id = result.lastInsertRowid;
  return row;
}
export function ownGiven(database: Database.Database, input: {resource:string;recordId:string;unitId:string;ownerId?:string;assigneeId?:string}) {
  return insertGiven(database, 'record_access', {resource:input.resource,record_id:input.recordId,
    unit_id:input.unitId,owner_id:input.ownerId ?? null,assignee_id:input.assigneeId ?? null});
}
export async function prepareGiven<T>(setup: () => T | Promise<T>): Promise<T> {
  try { return await setup(); }
  catch (error) { throw fixtureError(error); }
}

// Pure data mechanics: callers supply table names, locators and expected values.
// Never guess business identities, membership, statuses, defaults or FK parents.
function findRow(database: Database.Database, table: string, locator: Record<string, unknown>): Record<string, unknown> | undefined {
  const keys = Object.keys(locator);
  if (!keys.length || keys.some(k => locator[k] === undefined)) throw new Error('Given locator must be explicit and nonempty');
  const columns = database.prepare(`PRAGMA table_info(${ident(table)})`).all() as {name:string}[];
  if (!columns.length || keys.some(k => !columns.some(c => c.name === k))) throw new Error('Given locator references an unknown table/column');
  const rows = database.prepare(`SELECT * FROM ${ident(table)} WHERE ${keys.map(k => `${ident(k)} IS ?`).join(' AND ')} LIMIT 2`)
    .all(...keys.map(k => typeof locator[k] === 'boolean' ? Number(locator[k]) : locator[k])) as Record<string, unknown>[];
  if (rows.length > 1) throw new Error('Given locator is ambiguous: ' + table);
  return rows[0];
}
function ensureRow(database: Database.Database, table: string, locator: Record<string, unknown>, values: Record<string, unknown> = {}) {
  const keys = Object.keys(locator);
  const fields = database.prepare(`PRAGMA table_info(${ident(table)})`).all() as {name:string;pk:number}[];
  const unique = [fields.filter(f => f.pk).sort((a,b) => a.pk-b.pk).map(f => f.name)];
  const indexes = database.prepare(`PRAGMA index_list(${ident(table)})`).all() as {name:string;unique:number;partial:number}[];
  for (const index of indexes.filter(i => i.unique && !i.partial)) {
    const columns = database.prepare(`PRAGMA index_info(${ident(index.name)})`).all() as {name:string|null}[];
    if (columns.every(c => c.name !== null)) unique.push(columns.map(c => c.name!));
  }
  if (!keys.length || keys.some(k => locator[k] == null) || !unique.some(group => group.length && group.every(k => keys.includes(k))))
    throw new Error('ensureGiven needs a non-null PK/UNIQUE locator from the actual schema');
  for (const key of keys) if (key in values && values[key] !== locator[key]) throw new Error('Given locator/value conflict: ' + key);
  const expected = {...values, ...locator};
  const existing = findGiven(database, table, locator);
  if (existing) {
    for (const [key,value] of Object.entries(expected)) {
      if (value === undefined) throw new Error('Undefined Given value: ' + key);
      if (existing[key] !== (typeof value === 'boolean' ? Number(value) : value))
        throw new Error(`Existing Given differs at ${table}.${key}; use source-correct values or a distinct explicit locator`);
    }
    return existing;
  }
  insertGiven(database, table, expected);
  return findGiven(database, table, locator)!;
}
export async function sessionIdentity(session: HttpSession): Promise<{id:string;unitId:string;roles:string[];username:string;admin:boolean}> {
  const response = await sessionRequest(session, '/api/auth/me');
  const parsed = await readResponse<{user:{id:string;unitId:string;roles:string[];username:string;admin:boolean}}>(response);
  if (parsed.status !== 200 || !parsed.body?.user?.id || !parsed.body.user.unitId) throw new Error('Fixture cannot resolve actual session identity');
  return parsed.body.user;
}
export interface ReadResponse<T> { status:number; text:string; body:T; headers:Headers }
const responseBodies = new WeakMap<Response, Promise<ReadResponse<unknown>>>();
export async function readResponse<T = unknown>(response: Response): Promise<ReadResponse<T>> {
  let pending = responseBodies.get(response);
  if (!pending) {
    pending = (async () => {
      const text = await response.text();
      let body: unknown = undefined;
      if (text && response.headers.get('content-type')?.includes('application/json')) body = JSON.parse(text);
      return {status: response.status, text, body, headers: response.headers};
    })();
    responseBodies.set(response, pending);
  }
  return pending as Promise<ReadResponse<T>>;
}

function fixtureError(error: unknown): Error {
  if (error instanceof Error && error.message.startsWith('ARC_FIXTURE_SETUP:')) return error;
  return new Error('ARC_FIXTURE_SETUP: ' + (error instanceof Error ? error.message : String(error)), {cause:error});
}
export function insertGiven(database: Database.Database, table: string, values: Record<string,unknown>) {
  try { return insertRow(database, table, values); } catch (error) { throw fixtureError(error); }
}
export function findGiven(database: Database.Database, table: string, locator: Record<string,unknown>) {
  try { return findRow(database, table, locator); } catch (error) { throw fixtureError(error); }
}
export function ensureGiven(database: Database.Database, table: string, locator: Record<string,unknown>, values: Record<string,unknown> = {}) {
  try { return ensureRow(database, table, locator, values); } catch (error) { throw fixtureError(error); }
}
