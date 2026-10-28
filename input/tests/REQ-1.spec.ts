// requirement: REQ-1 — Register; the two teaching scenarios.
import { expect, test } from '@playwright/test';
import { EXISTING_ACCOUNT, button, entry, expectSignedIn, expectSignedOut,
  fillRegistration, newAccount, openRegistration, registerAccount } from './helpers';

test('SCN-REQ-1-01: Register with a new username and remain signed in after refresh', async ({ page }) => {
  await entry(page);
  const account = newAccount();
  await registerAccount(page, account);
  await page.reload();
  await expectSignedIn(page, account);
});

test('SCN-REQ-1-02: Reject an existing username without creating a session', async ({ page }) => {
  const account = { ...newAccount(), username: EXISTING_ACCOUNT.username };
  await entry(page);
  await openRegistration(page);
  await fillRegistration(page, account);
  await button(page, 'Next step').click();
  await expect(page.getByRole('alert')).toBeVisible();
  await page.goto('/');
  await page.reload();
  await expectSignedOut(page);
});
