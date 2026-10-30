// requirement: REQ-4 — Logout.
import { expect, test } from '@playwright/test';
import { entry, expectSignedIn, expectSignedOut, newAccount, registerAccount, signIn, signOut } from './helpers';

test('SCN-REQ-4-01: Log out and remain signed out after refresh', async ({ page }) => {
  const account = newAccount();
  await entry(page);
  await registerAccount(page, account);
  await signOut(page, account);
  await page.reload();
  await expectSignedOut(page);
  await expect(page.getByText(account.username, { exact: true })).toHaveCount(0);
});

test('SCN-REQ-4-02: Log in again after logout', async ({ page }) => {
  const account = newAccount();
  await entry(page);
  await registerAccount(page, account);
  await signOut(page, account);
  await signIn(page, account.username, account.password);
  await expectSignedIn(page, account);
  await page.reload();
  await expectSignedIn(page, account);
});
