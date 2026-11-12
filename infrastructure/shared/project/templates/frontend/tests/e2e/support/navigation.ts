// Compiler-owned navigation mechanics. Every path, action and landmark comes from source tests.
import { expect, test } from '@playwright/test';
import type { Locator, Page } from '@playwright/test';

export interface NavigationCheck {
  trigger: Locator;
  targetURL: string | RegExp;
  landmark: Locator;
  reload?: boolean;
  history?: { sourceURL: string | RegExp; sourceLandmark: Locator };
}

/** Prove actual click-through navigation; direct goto alone is not reachability evidence. */
export async function navigateAndAssert(page: Page, check: NavigationCheck): Promise<void> {
  const from = new URL(page.url()).pathname;
  await check.trigger.click();
  await expect(page).toHaveURL(check.targetURL);
  await expect(check.landmark).toBeVisible();
  const to = new URL(page.url()).pathname;
  if (check.reload) {
    await page.reload();
    await expect(page).toHaveURL(check.targetURL);
    await expect(check.landmark).toBeVisible();
  }
  if (check.history) {
    await page.goBack();
    await expect(page).toHaveURL(check.history.sourceURL);
    await expect(check.history.sourceLandmark).toBeVisible();
    await page.goForward();
    await expect(page).toHaveURL(check.targetURL);
    await expect(check.landmark).toBeVisible();
  }
  test.info().annotations.push({ type: 'arc-navigation', description: JSON.stringify({
    from, to, reload: !!check.reload, history: !!check.history
  }) });
}

/** Use the single named combobox, then the real visible portal option. */
export async function chooseNamedOption(page: Page, label: string, option: string, scope: Page | Locator = page): Promise<void> {
  const control = scope.getByRole('combobox', { name: label, exact: true });
  await expect(control).toHaveCount(1);
  await control.click();
  await page.getByRole('option', { name: option, exact: true }).click();
}
