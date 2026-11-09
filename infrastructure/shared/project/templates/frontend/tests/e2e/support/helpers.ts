// Compiler-owned browser setup helpers. Scenario When actions must still use real UI.
import type { Page, APIRequestContext } from '@playwright/test';
export { insertGiven, ownGiven, prepareGiven } from '../../../../backend/tests/support/helpers.js';
export interface BrowserSession { request: APIRequestContext; csrfToken: string }
export async function loginGiven(page: Page, account: {username:string;password:string;unit?:string}): Promise<BrowserSession> {
  const response = await page.request.post('/api/auth/login', {data:account});
  if (response.status() !== 200) throw new Error(`Fixture login failed: ${response.status()} ${await response.text()}`);
  const body = await response.json();
  return {request:page.request,csrfToken:body.csrfToken};
}
export async function browserRequest(session: BrowserSession, path: string,
    options: {method?:string;data?:unknown;idempotencyKey?:string;headers?:Record<string,string>} = {}) {
  const response = await session.request.fetch(path, {method:options.method ?? 'GET',data:options.data,
    headers:{'X-CSRF-Token':session.csrfToken,
      ...(options.idempotencyKey ? {'Idempotency-Key':options.idempotencyKey} : {}), ...options.headers}});
  if (response.ok() && response.headers()['content-type']?.includes('application/json')) {
    // APIResponse.json() may be called again by source assertions.
    const body = await response.json();
    if (body.csrfToken) session.csrfToken = body.csrfToken;
  }
  return response;
}
