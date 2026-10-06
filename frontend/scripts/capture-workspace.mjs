import process from 'node:process';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath, URL } from 'node:url';
import { randomUUID } from 'node:crypto';
import { chromium, expect } from '@playwright/test';

const baseURL = process.env.SCOPEGATE_WEB_URL ?? 'http://localhost:5187';
const output = fileURLToPath(new URL('../../artifacts/browser/screenshots/', import.meta.url));
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  channel:
    process.env.SCOPEGATE_BROWSER_CHANNEL ?? (process.platform === 'darwin' ? 'chrome' : undefined),
});
const context = await browser.newContext({ baseURL, viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const organization = '/api/v1/organizations/20000000-0000-4000-8000-000000000001';
let invitationId;
let headers;
async function capture(name) {
  await page.evaluate(() => globalThis.document.fonts.ready);
  const fullPage = (await page.getByRole('dialog').count()) === 0 && name !== '09-audit-activity';
  await page.screenshot({ path: `${output}${name}.png`, fullPage, animations: 'disabled' });
  process.stdout.write(`Captured ${name}.png\n`);
}
async function navigate(name) {
  const menu = page.getByRole('button', { name: 'Open navigation', exact: true });
  if (await menu.isVisible()) await menu.click();
  await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByRole('button', { name, exact: true })
    .click();
}
async function login(target, name, returnTo = '/workspace') {
  await target.goto(`/auth/login?return_to=${encodeURIComponent(returnTo)}`);
  await target.getByRole('button', { name: new RegExp(name) }).click();
}
async function readyOverview() {
  await expect(page.getByRole('heading', { name: 'Good to see you, Amelia.' })).toBeVisible();
  await expect(page.locator('.resource-preview')).toHaveCount(3);
  const stats = page.locator('.stats-grid .stat-card strong');
  await expect(stats).toHaveCount(3);
  for (const stat of await stats.all()) await expect(stat).toHaveText(/^\d+$/);
  await expect(page.locator('.activity-preview .audit-event').first()).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
}
try {
  await page.goto('/');
  await expect(page.getByRole('link', { name: 'Sign in to your workspace' })).toBeVisible();
  await capture('01-sign-in');
  await login(page, 'Amelia Brooks');
  await readyOverview();
  await capture('02-overview');
  await navigate('Resource library');
  await expect(page.getByRole('heading', { name: 'Market pulse', exact: true })).toBeVisible();
  await capture('03-resource-library');
  await page.getByLabel('Resource language', { exact: true }).selectOption('pt');
  await expect(page.getByRole('heading', { name: 'Pulso de mercado' })).toBeVisible();
  await capture('04-localized-library');
  await navigate('Members & access');
  await expect(page.getByRole('row').filter({ hasText: 'Jonah Reed' })).toBeVisible();
  await capture('05-members');
  await page
    .getByRole('row')
    .filter({ hasText: 'Jonah Reed' })
    .getByRole('button', { name: 'Manage access' })
    .click();
  await page.getByRole('checkbox', { name: /Growth signals/ }).check();
  await page
    .getByRole('textbox', { name: 'Reason for this change' })
    .fill('Approved growth analysis assignment for Harbor');
  await page.getByRole('button', { name: 'Preview change' }).click();
  await expect(page.getByText('1 addition', { exact: true })).toBeVisible();
  await capture('06-grant-change-review');
  await page.keyboard.press('Escape');
  await navigate('Invitations');
  await expect(page.getByRole('row').filter({ hasText: 'expired@example.test' })).toContainText(
    'Acceptance window closed',
  );
  await expect(page.getByRole('row').filter({ hasText: 'failed@example.test' })).toContainText(
    'Delivery attempts exhausted',
  );
  await expect(page.locator('.mailbox-list article').first()).toBeVisible();
  await capture('07-invitation-history');
  await page.getByRole('button', { name: 'Create invitation', exact: true }).click();
  await page.getByRole('textbox', { name: 'Recipient email' }).fill('taylor@example.test');
  await page.getByRole('checkbox', { name: /Market pulse/ }).check();
  await page.getByRole('checkbox', { name: /Audience atlas/ }).check();
  await page.getByRole('button', { name: 'Review invitation' }).click();
  await expect(page.locator('.review-resources')).toContainText('Audience atlas');
  await capture('08-invitation-plan-review');
  await page.keyboard.press('Escape');
  await navigate('Audit activity');
  await expect(page.locator('.audit-event').first()).toBeVisible();
  await page.getByRole('button', { name: 'Change details' }).first().click();
  await expect(page.locator('.audit-details')).toBeVisible();
  await capture('09-audit-activity');
  await navigate('Overview');
  await readyOverview();
  await page.setViewportSize({ width: 768, height: 1000 });
  await capture('10-overview-tablet');
  await page.setViewportSize({ width: 375, height: 950 });
  await capture('11-overview-mobile');
  await navigate('Resource library');
  await expect(page.locator('.resource-card').first()).toBeVisible();
  await capture('12-library-mobile');
  await page.setViewportSize({ width: 1440, height: 1000 });

  const session = await (await page.request.get('/api/v1/me')).json();
  headers = { 'X-CSRF-Token': session.csrf_token, Origin: baseURL };
  const messages = await (await page.request.get(`${organization}/mailbox`)).json();
  const previous = new Set(messages.items.map((message) => message.accept_url));
  const created = await page.request.post(`${organization}/invitations`, {
    headers: { ...headers, 'Idempotency-Key': randomUUID() },
    data: {
      email: 'morgan@example.test',
      expires_in_hours: 24,
      resources: [
        {
          project_id: '30000000-0000-4000-8000-000000000001',
          resource_id: '40000000-0000-4000-8000-000000000001',
        },
      ],
    },
  });
  expect(created.status()).toBe(201);
  invitationId = (await created.json()).id;
  let delivery;
  await expect
    .poll(
      async () => {
        const mailbox = await (await page.request.get(`${organization}/mailbox`)).json();
        delivery = mailbox.items.find(
          (message) =>
            message.recipient_email === 'morgan@example.test' && !previous.has(message.accept_url),
        );
        return Boolean(delivery);
      },
      { timeout: 15_000 },
    )
    .toBe(true);
  const recipientContext = await browser.newContext({
    baseURL,
    viewport: { width: 1440, height: 1000 },
  });
  const recipient = await recipientContext.newPage();
  await recipient.goto(delivery.accept_url);
  await recipient.getByRole('link', { name: 'Sign in to review' }).click();
  await recipient.getByRole('button', { name: /Morgan Lane/ }).click();
  await expect(
    recipient.getByRole('heading', { name: 'Your explicit resource plan' }),
  ).toBeVisible();
  await recipient.evaluate(() => globalThis.document.fonts.ready);
  await recipient.screenshot({
    path: `${output}13-recipient-plan.png`,
    fullPage: true,
    animations: 'disabled',
  });
  process.stdout.write('Captured 13-recipient-plan.png\n');
  await recipientContext.close();

  const reviewerContext = await browser.newContext({
    baseURL,
    viewport: { width: 1440, height: 1000 },
  });
  const reviewer = await reviewerContext.newPage();
  await login(reviewer, 'Rowan Vale');
  await reviewer
    .getByRole('navigation', { name: 'Main navigation' })
    .getByRole('button', { name: 'Migration review', exact: true })
    .click();
  await expect(reviewer.locator('.ledger-item').first()).toBeVisible();
  await reviewer.evaluate(() => globalThis.document.fonts.ready);
  await reviewer.screenshot({
    path: `${output}14-migration-review.png`,
    fullPage: true,
    animations: 'disabled',
  });
  process.stdout.write('Captured 14-migration-review.png\n');
  await reviewerContext.close();
} finally {
  if (invitationId && headers) {
    const revoked = await page.request.post(`${organization}/invitations/${invitationId}/revoke`, {
      headers: { ...headers, 'Idempotency-Key': randomUUID() },
    });
    expect(revoked.status()).toBe(200);
  }
  await context.close();
  await browser.close();
}
