// requirement: REQ-2 — Login; the two teaching scenarios.
import { expect, test } from '@playwright/test';
import { EXISTING_ACCOUNT, entry, expectSignedIn, expectSignedOut, signIn } from './helpers';

test('SCN-REQ-2-01: Log in with the correct password and remain signed in after refresh', async ({ page }) => {
  await entry(page);
  await signIn(page, EXISTING_ACCOUNT.username, EXISTING_ACCOUNT.password);
  await expectSignedIn(page, EXISTING_ACCOUNT);
  await page.reload();
  await expectSignedIn(page, EXISTING_ACCOUNT);
});

test('SCN-REQ-2-02: Reject an incorrect password without creating a session', async ({ page }) => {
  await entry(page);
  await signIn(page, EXISTING_ACCOUNT.username, 'WrongSmoke!2026');
  await expect(page.getByRole('alert')).toBeVisible();
  await page.goto('/');
  await page.reload();
  await expectSignedOut(page);
});
