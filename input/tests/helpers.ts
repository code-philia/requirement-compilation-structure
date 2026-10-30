import { randomUUID } from 'node:crypto';
import { expect, type Locator, type Page } from '@playwright/test';

type Surface = Page | Locator;
export const AGREEMENT =
  'I have read and agree to abide by Terms of Service and Privacy Policy of 12306.cn.';
export const link = (surface: Surface, name: string) => surface.getByRole('link', { name, exact: true });
export const button = (surface: Surface, name: string) => surface.getByRole('button', { name, exact: true });
export const textbox = (surface: Surface, name: string) => surface.getByRole('textbox', { name, exact: true });
// Native password inputs have no implicit textbox role; locate them by the required label.
export const passwordField = (surface: Surface, name: string) => surface.getByLabel(name, { exact: true });

// Seeded by the scenario environment; tests must not use registration to create this Given data.
export const EXISTING_ACCOUNT = {
  username: 'taken_traveler', email: 'taken.traveler@example.com', password: 'TakenSmoke!2026',
};

export async function entry(page: Page) { await page.goto('/'); }
export async function openRegistration(page: Page) {
  await link(page, 'Register').click();
  await expect(page).toHaveURL(/\/register\/?$/);
  await expect(page.getByRole('combobox', { name: 'Nationality', exact: true })).toBeVisible();
}
export async function openLogin(page: Page) {
  await link(page, 'Login').click();
  await expect(page).toHaveURL(/\/login\/?$/);
  await expect(textbox(page, 'Email/Username/Mobile number')).toBeVisible();
}
export function newAccount() {
  const identity = randomUUID().replace(/-/g, '').slice(0, 20);
  return {
    username: `smoke-${identity}`, email: `smoke-${identity}@example.com`,
    name: `Traveler ${identity}`, passport: `P${identity}`, password: 'Valid-password-123!',
  };
}
export type Account = ReturnType<typeof newAccount>;
export async function expectSignedIn(page: Page, account: { username: string }) {
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByText(account.username, { exact: true })).toBeVisible();
  await expect(link(page, 'Register')).toHaveCount(0);
  await expect(link(page, 'Login')).toHaveCount(0);
  await expect(button(page, 'Logout')).toBeVisible();
}
export async function expectSignedOut(page: Page) {
  await expect(link(page, 'Register')).toBeVisible();
  await expect(link(page, 'Login')).toBeVisible();
  await expect(button(page, 'Logout')).toHaveCount(0);
}
export async function fillRegistration(page: Page, account: Account) {
  const nationality = page.getByRole('combobox', { name: 'Nationality', exact: true });
  try {
    await nationality.selectOption({ label: 'China' }, { timeout: 1_000 });
  } catch {
    await nationality.click();
    await page.getByRole('option', { name: 'China', exact: true }).click();
  }
  await textbox(page, 'Name').fill(account.name);
  await textbox(page, 'Passport number').fill(account.passport);
  await textbox(page, 'Passport expiration date').fill('2099-12-31');
  await textbox(page, 'Date of birth').fill('1995-06-15');
  await page.getByRole('radiogroup', { name: 'Gender', exact: true })
    .getByRole('radio', { name: 'Male', exact: true }).check();
  await textbox(page, 'Username').fill(account.username);
  await passwordField(page, 'Password').fill(account.password);
  await passwordField(page, 'Confirm Password').fill(account.password);
  await textbox(page, 'Email address').fill(account.email);
  await page.getByRole('checkbox', { name: AGREEMENT, exact: true }).check();
}
export async function registerAccount(page: Page, account: Account) {
  await openRegistration(page);
  await fillRegistration(page, account);
  await button(page, 'Next step').click();
  await expectSignedIn(page, account);
}
export async function signIn(page: Page, identifier: string, password: string) {
  await openLogin(page);
  await textbox(page, 'Email/Username/Mobile number').fill(identifier);
  await passwordField(page, 'Password').fill(password);
  await button(page, 'LOGIN').click();
}

export async function signOut(page: Page, account: { username: string }) {
  await button(page, 'Logout').click();
  await expect(page).toHaveURL(/\/$/);
  await expectSignedOut(page);
  await expect(page.getByText(account.username, { exact: true })).toHaveCount(0);
}
