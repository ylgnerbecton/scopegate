import { mkdir, writeFile } from 'node:fs/promises';
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Locator, type Page } from '@playwright/test';

const evidence = new WeakMap<Page, { scans: unknown[]; journeys: unknown[] }>();
function pageEvidence(page: Page) {
  if (!evidence.has(page)) evidence.set(page, { scans: [], journeys: [] });
  return evidence.get(page)!;
}
export async function writeBrowserEvidence(name: string, body: unknown) {
  await mkdir('../artifacts/browser', { recursive: true });
  await writeFile(`../artifacts/browser/${name}.json`, `${JSON.stringify(body, null, 2)}\n`);
}
export async function writeInteractionEvidence(page: Page) {
  const current = pageEvidence(page);
  expect(current.journeys).toHaveLength(3);
  expect(current.scans.length).toBeGreaterThanOrEqual(15);
  await writeBrowserEvidence('interaction-evidence', {
    schemaVersion: 1,
    recordedAt: new Date().toISOString(),
    test: test.info().title,
    viewports: [375, 768, 1440],
    disabledRules: [],
    ...current,
  });
}

/** Real Tab traversal: never moves focus with a DOM or locator focus call. */
export class KeyboardJourney {
  private steps: { action: string; control: string; width: number }[] = [];
  constructor(
    private page: Page,
    private width: number,
  ) {}

  private async tabTo(control: Locator) {
    await expect(control).toBeVisible();
    for (let count = 0; count < 250; count++) {
      if (await control.evaluate((node) => node === document.activeElement)) {
        const focused = await control.evaluate((node) => {
          const rect = node.getBoundingClientRect();
          const style = getComputedStyle(node);
          return {
            left: rect.left,
            right: rect.right,
            top: rect.top,
            bottom: rect.bottom,
            viewportWidth: innerWidth,
            viewportHeight: innerHeight,
            outline: style.outlineStyle,
            outlineWidth: parseFloat(style.outlineWidth),
            name:
              node.getAttribute('aria-label') ??
              node.textContent?.trim().slice(0, 80) ??
              node.tagName,
          };
        });
        expect(
          focused.left,
          'Focused action remains inside the horizontal viewport',
        ).toBeGreaterThanOrEqual(-1);
        expect(focused.right).toBeLessThanOrEqual(focused.viewportWidth + 1);
        expect(focused.top).toBeGreaterThanOrEqual(-1);
        expect(focused.bottom).toBeLessThanOrEqual(focused.viewportHeight + 1);
        expect(focused.outline).not.toBe('none');
        expect(focused.outlineWidth).toBeGreaterThanOrEqual(2);
        this.steps.push({
          action: 'Tab to visible focus',
          control: focused.name,
          width: this.width,
        });
        return;
      }
      await this.page.keyboard.press('Tab');
      const hiddenFocus = await this.page.evaluate(() => {
        const active = document.activeElement;
        if (!active || active === document.body) return false;
        const box = active.getBoundingClientRect();
        return box.right < 0 || box.left > innerWidth;
      });
      expect(hiddenFocus, 'Tab order must not enter a closed off-screen navigation panel').toBe(
        false,
      );
    }
    throw new Error('The requested control was unreachable after a complete keyboard traversal.');
  }
  async activate(control: Locator) {
    await this.tabTo(control);
    await this.page.keyboard.press('Enter');
    this.steps.push({ action: 'Enter', control: 'Activate focused action', width: this.width });
  }
  async toggle(control: Locator) {
    await this.tabTo(control);
    await this.page.keyboard.press('Space');
    this.steps.push({
      action: 'Space',
      control: 'Toggle focused resource or confirmation',
      width: this.width,
    });
  }
  async type(control: Locator, value: string) {
    await this.tabTo(control);
    await this.page.keyboard.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A');
    await this.page.keyboard.insertText(value);
    this.steps.push({
      action: 'Type',
      control: 'Enter a synthetic recipient or decision reason',
      width: this.width,
    });
  }
  async navigate(label: string) {
    const menu = this.page.getByRole('button', { name: 'Open navigation', exact: true });
    if (await menu.isVisible()) {
      await this.activate(menu);
      await scanAccessibility(this.page, `navigation-${this.width}`);
    }
    await this.activate(
      this.page
        .getByRole('navigation', { name: 'Main navigation' })
        .getByRole('button', { name: label, exact: true }),
    );
    await expect(this.page.getByRole('heading', { name: label, exact: true })).toBeVisible();
  }
  async startInvitationHistory() {
    await expect(this.page.getByRole('table')).toBeVisible();
    const pagination = this.page.locator('.pagination');
    if (await pagination.count()) {
      await expect(pagination).toContainText('Page 1 ·');
      await expect(
        pagination.getByRole('button', { name: 'Previous', exact: true }),
      ).toBeDisabled();
    }
  }
  async findInvitation(recipientEmail: string) {
    const row = this.page.getByRole('row').filter({ hasText: recipientEmail });
    const pagination = this.page.locator('.pagination');
    for (let currentPage = 1; currentPage <= 20; currentPage++) {
      await expect(this.page.getByRole('table')).toBeVisible();
      if (await row.count()) {
        await expect(row).toContainText('pending');
        this.steps.push({
          action: 'Locate confirmed invitation',
          control: `Invitation history page ${currentPage}`,
          width: this.width,
        });
        return;
      }
      const next = pagination.getByRole('button', { name: 'Next', exact: true });
      expect(await next.count(), 'The confirmed invitation must occur in bounded history').toBe(1);
      await expect(next).toBeEnabled();
      expect(currentPage, 'Invitation history verification is bounded to 20 pages').toBeLessThan(
        20,
      );
      const pageResponse = this.page.waitForResponse((response) => {
        const url = new URL(response.url());
        return (
          response.request().method() === 'GET' &&
          /^\/api\/v1\/organizations\/[^/]+\/invitations$/.test(url.pathname) &&
          url.searchParams.get('limit') === '25' &&
          url.searchParams.has('cursor')
        );
      });
      await this.activate(next);
      const response = await pageResponse;
      expect(response.status(), 'Keyboard pagination receives the actual history page').toBe(200);
      await expect(pagination).toContainText(`Page ${currentPage + 1} ·`);
      await expect(this.page.getByRole('table')).toBeVisible();
      this.steps.push({
        action: 'Next page by keyboard',
        control: `Invitation history page ${currentPage + 1}`,
        width: this.width,
      });
    }
    throw new Error('The confirmed invitation was not found within 20 history pages.');
  }
  async attachEvidence() {
    expect(await this.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    pageEvidence(this.page).journeys.push({
      viewport: this.width,
      input: 'keyboard only',
      completed: [
        'invitation create/review/revoke',
        'grant add/review/confirm',
        'grant remove/review/confirmation',
        'Escape and trigger focus restoration',
      ],
      steps: this.steps,
    });
    await test.info().attach(`keyboard-journey-${this.width}`, {
      body: JSON.stringify(
        {
          viewport: this.width,
          input: 'Tab, Enter, Space, text entry, Escape only',
          completed: [
            'invitation create/review/revoke',
            'grant add/review/confirm',
            'grant remove/review/confirmation',
            'Escape and trigger focus restoration',
          ],
          steps: this.steps,
        },
        null,
        2,
      ),
      contentType: 'application/json',
    });
  }
}

export async function scanAccessibility(page: Page, name: string) {
  const result = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze();
  // Keep evidence useful without copying mailbox links or other DOM content.
  const violations = result.violations.map(({ id, impact, nodes }) => ({
    id,
    impact,
    nodes: nodes.map(({ target, failureSummary }) => ({ target, failureSummary })),
  }));
  await test.info().attach(`accessibility-${name}`, {
    body: JSON.stringify(
      {
        name,
        engine: result.testEngine,
        tags: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'],
        passedRules: result.passes.map(({ id }) => id),
        incompleteRules: result.incomplete.map(({ id, nodes }) => ({
          id,
          targets: nodes.map(({ target }) => target),
        })),
        violations,
      },
      null,
      2,
    ),
    contentType: 'application/json',
  });
  expect(
    result.passes.length,
    'The accessibility scan must exercise actual rendered content',
  ).toBeGreaterThan(10);
  expect(violations, `Accessibility scan ${name}`).toEqual([]);
  pageEvidence(page).scans.push({
    name,
    engine: result.testEngine,
    passedRules: result.passes.map(({ id }) => id),
    incompleteRules: result.incomplete.map(({ id, nodes }) => ({
      id,
      targets: nodes.map(({ target }) => target),
    })),
    violations,
  });
}
