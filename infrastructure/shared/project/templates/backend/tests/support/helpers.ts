// Compiler-owned helpers. Expected business values always come from source requirements.
import type Database from 'better-sqlite3';
import { randomUUID } from 'node:crypto';

export interface TestAccount { username: string; password: string; unit?: string }
export interface HttpSession { baseURL: string; cookie: string; csrfToken: string }
const ident = (name: string) => {
  if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(name)) throw new Error('Invalid fixture identifier');
  return '"' + name + '"';
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
export function insertGiven(database: Database.Database, table: string, values: Record<string,unknown>) {
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
  catch (error) { throw new Error('ARC_FIXTURE_SETUP: ' + (error instanceof Error ? error.message : String(error)), {cause:error}); }
}
