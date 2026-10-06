import { expect, test, type Page } from '@playwright/test';
import {
  KeyboardJourney,
  scanAccessibility,
  writeBrowserEvidence,
  writeInteractionEvidence,
} from './keyboard';

async function login(page: Page, name: string) {
  await page.goto('/auth/login?return_to=/workspace');
  await page.getByRole('button', { name: new RegExp(name) }).click();
  await expect(page).toHaveURL(/localhost:5187\/workspace/);
  await expect(page.locator('#organization')).toBeVisible();
}
async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Sign in to your workspace' })).toBeVisible();
}
async function navigate(page: Page, label: string) {
  await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByRole('button', { name: label, exact: true })
    .click();
}
async function verifiedRead(page: Page, path: string) {
  const response = await page.request.get(path);
  const body = await response.json();
  expect(
    response.status(),
    `Read ${path.split('?')[0]} returned ${response.status()} (${body.error?.code ?? 'unexpected_response'})`,
  ).toBe(200);
  return body;
}

async function prepareRecipient(page: Page) {
  const organization = '/api/v1/organizations/20000000-0000-4000-8000-000000000001';
  const session = await (await page.request.get('/api/v1/me')).json();
  const headers = { 'X-CSRF-Token': session.csrf_token, Origin: 'http://localhost:5187' };
  const invitations = await (
    await page.request.get(`${organization}/invitations?limit=100`)
  ).json();
  for (const invitation of invitations.items) {
    if (invitation.recipient_email === 'morgan@example.test' && invitation.state === 'pending') {
      const revoked = await page.request.post(
        `${organization}/invitations/${invitation.id}/revoke`,
        {
          headers: { ...headers, 'Idempotency-Key': crypto.randomUUID() },
        },
      );
      expect(revoked.status()).toBe(200);
    }
  }
  const members = await (await page.request.get(`${organization}/memberships?limit=100`)).json();
  const recipient = members.items.find(
    (member: { email: string }) => member.email === 'morgan@example.test',
  );
  if (!recipient) return;
  const path = `${organization}/memberships/${recipient.id}/projects/30000000-0000-4000-8000-000000000001/grants`;
  const snapshot = await (await page.request.get(`${path}?limit=100`)).json();
  const active = snapshot.items
    .filter((grant: { state: string }) => grant.state === 'active')
    .map((grant: { resource_id: string }) => grant.resource_id);
  if (!active.length) return;
  const cleared = await page.request.patch(path, {
    headers: {
      ...headers,
      'Idempotency-Key': crypto.randomUUID(),
      'If-Match': `"v${snapshot.access_version}"`,
    },
    data: {
      add: [],
      remove: active,
      reason: 'Prepare the scoped synthetic invitation verification',
    },
  });
  expect(cleared.status()).toBe(200);
}

test('verified invitation, scoped grant diff, resource use, revocation, and audit against the real services', async ({
  page,
}) => {
  test.setTimeout(90_000);
  await login(page, 'Amelia Brooks');
  await prepareRecipient(page);
  await navigate(page, 'Invitations');
  const mailbox = await (
    await page.request.get('/api/v1/organizations/20000000-0000-4000-8000-000000000001/mailbox')
  ).json();
  const previousLinks = new Set(
    mailbox.items.map((message: { accept_url: string }) => message.accept_url),
  );
  await page.getByRole('button', { name: 'Create invitation', exact: true }).click();
  await page.getByRole('textbox', { name: 'Recipient email' }).fill('morgan@example.test');
  await page.getByRole('checkbox', { name: /Market pulse/ }).check();
  await page.getByRole('button', { name: 'Review invitation', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'A precise welcome for morgan@example.test' }),
  ).toBeVisible();
  await expect(page.locator('.review-resources')).toContainText('Market pulse');
  await page.getByRole('button', { name: 'Create verified invitation' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Invitation created.' })).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Open invitation' }).first()).toBeVisible({
    timeout: 15_000,
  });
  await expect
    .poll(
      async () => {
        const href = await page
          .getByRole('link', { name: 'Open invitation' })
          .first()
          .getAttribute('href');
        return Boolean(href && !previousLinks.has(href));
      },
      { timeout: 15_000 },
    )
    .toBe(true);
  const invitation = await page
    .getByRole('link', { name: 'Open invitation' })
    .first()
    .getAttribute('href');
  await signOut(page);
  await page.goto(invitation!);
  await page.getByRole('link', { name: 'Sign in to review' }).click();
  await page.getByRole('button', { name: /Morgan Lane/ }).click();
  await expect(page.getByRole('heading', { name: 'Your explicit resource plan' })).toBeVisible();
  await expect(page).toHaveURL(/\/invitations\/accept$/);
  await scanAccessibility(page, 'verified-recipient-plan');
  await page.getByRole('button', { name: 'Accept invitation', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Invitation accepted.' })).toBeVisible();
  await page.getByRole('button', { name: 'Enter Cedar Studio' }).click();
  await expect(page.getByRole('heading', { name: 'Market pulse', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Open resource', exact: true }).first().click();
  await page.getByRole('button', { name: 'Open protected resource' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Access confirmed.' })).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click();
  await signOut(page);
  await login(page, 'Amelia Brooks');
  await navigate(page, 'Members & access');
  const member = page.getByRole('row').filter({ hasText: 'Morgan Lane' });
  await member.getByRole('button', { name: 'Manage access' }).click();
  await page.getByRole('checkbox', { name: /Audience atlas/ }).check();
  await page
    .getByRole('textbox', { name: 'Reason for this change' })
    .fill('Approved audience research assignment');
  await page.getByRole('button', { name: 'Preview change' }).click();
  await expect(page.getByText('1 addition', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Confirm access change' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Access updated.' })).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click();
  await member.getByRole('button', { name: 'Manage access' }).click();
  await expect(page.getByText('2 active grants', { exact: true })).toBeVisible();
  await page.getByRole('checkbox', { name: /Market pulse/ }).uncheck();
  await page.getByRole('checkbox', { name: /Audience atlas/ }).uncheck();
  await page
    .getByRole('textbox', { name: 'Reason for this change' })
    .fill('Project assignment completed');
  await page.getByRole('button', { name: 'Preview change' }).click();
  await expect(page.getByRole('button', { name: 'Confirm access change' })).toBeDisabled();
  await page.getByRole('checkbox', { name: /I confirm removal of 2 resource grants/ }).check();
  await page.getByRole('button', { name: 'Confirm access change' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Access updated.' })).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click();
  await navigate(page, 'Audit activity');
  await expect(page.locator('.audit-event')).not.toHaveCount(0);
  await signOut(page);
  await login(page, 'Morgan Lane');
  await navigate(page, 'Resource library');
  await expect(page.getByRole('heading', { name: 'No resources granted yet' })).toBeVisible();
  const denied = await page.request.post(
    '/api/v1/organizations/20000000-0000-4000-8000-000000000001/projects/30000000-0000-4000-8000-000000000001/report-configs',
    {
      headers: {
        'X-CSRF-Token': (await (await page.request.get('/api/v1/me')).json()).csrf_token,
        'Idempotency-Key': crypto.randomUUID(),
        Origin: 'http://localhost:5187',
      },
      data: {
        name: 'Revocation verification',
        resource_ids: ['40000000-0000-4000-8000-000000000001'],
      },
    },
  );
  expect(denied.status()).toBeGreaterThanOrEqual(400);
  expect(denied.status()).toBeLessThan(500);
});

test('delivery and expiry remain distinct while competing migration evidence requires explicit review', async ({
  page,
}) => {
  await login(page, 'Amelia Brooks');
  await navigate(page, 'Invitations');
  await scanAccessibility(page, 'invitation-history');
  const expired = page.getByRole('row').filter({ hasText: 'expired@example.test' });
  await expect(expired).toContainText('expired');
  await expect(expired).toContainText('Acceptance window closed');
  await expect(expired.getByRole('button', { name: /Resend invitation/ })).toHaveCount(0);
  const failed = page.getByRole('row').filter({ hasText: 'failed@example.test' });
  await expect(failed).toContainText('pending');
  await expect(failed).toContainText('failed');
  await expect(failed).toContainText('Delivery attempts exhausted');
  await expect(failed.getByRole('button', { name: /Resend invitation/ })).toBeEnabled();
  await signOut(page);
  await login(page, 'Rowan Vale');
  await navigate(page, 'Migration review');
  await expect(page.locator('.ledger-item').first()).toBeVisible();
  await scanAccessibility(page, 'migration-review');
  await expect(page.getByRole('button', { name: /cutover/i })).toHaveCount(0);
  const organization = '/api/v1/organizations/20000000-0000-4000-8000-000000000001';
  const runs = await (await page.request.get(`${organization}/migration-runs?limit=100`)).json();
  const run = runs.items[0];
  const ledger = await (
    await page.request.get(`${organization}/migration-runs/${run.id}/items?limit=100`)
  ).json();
  const original = ledger.items[0];
  const path = `${organization}/migration-runs/${run.id}/items/${original.id}`;
  const session = await (await page.request.get('/api/v1/me')).json();
  const headers = { 'X-CSRF-Token': session.csrf_token, Origin: 'http://localhost:5187' };
  const reason = 'Preserved draft: verify the source evidence before transition';
  const payload = {
    outcome: 'review_required',
    target_kind: original.target_kind ?? null,
    target_id: original.target_id ?? null,
    assigned_owner_user_id: session.id,
    decision_reason: 'Competing reviewer: the source mapping still needs investigation',
  };
  try {
    await page
      .locator('.ledger-item')
      .filter({ hasText: original.source_key })
      .getByRole('button', { name: 'Review decision' })
      .click();
    await page
      .getByRole('combobox', { name: 'Decision', exact: true })
      .selectOption('review_required');
    await page.getByRole('textbox', { name: 'Evidence and decision reason' }).fill(reason);
    const competing = await page.request.patch(path, {
      headers: {
        ...headers,
        'Idempotency-Key': crypto.randomUUID(),
        'If-Match': `"v${original.review_version}"`,
      },
      data: payload,
    });
    expect(competing.status()).toBe(200);
    await page.getByRole('button', { name: 'Record reviewed decision' }).click();
    await expect(page.getByRole('alert')).toBeVisible();
    await page
      .getByRole('button', { name: 'Load competing decision and preserve my draft' })
      .click();
    await expect(page.getByRole('textbox', { name: 'Evidence and decision reason' })).toHaveValue(
      reason,
    );
    await expect(page.locator('.conflict-review')).toContainText(payload.decision_reason);
    await expect(page.getByRole('button', { name: 'Record reviewed decision' })).toBeDisabled();
    await page
      .getByRole('checkbox', { name: 'I reviewed the competing decision and intend to replace it' })
      .check();
    await page.getByRole('button', { name: 'Record reviewed decision' }).click();
    await expect(
      page.getByRole('status').filter({ hasText: 'Decision recorded at review' }),
    ).toBeVisible();
  } finally {
    const current = await (
      await page.request.get(`${organization}/migration-runs/${run.id}/items?limit=100`)
    ).json();
    const item = current.items.find((entry: { id: string }) => entry.id === original.id);
    const restored = await page.request.patch(path, {
      headers: {
        ...headers,
        'Idempotency-Key': crypto.randomUUID(),
        'If-Match': `"v${item.review_version}"`,
      },
      data: {
        outcome: original.outcome,
        target_kind: original.target_kind ?? null,
        target_id: original.target_id ?? null,
        assigned_owner_user_id: original.assigned_owner_user_id ?? null,
        decision_reason:
          original.decision_reason || 'Restore synthetic reconciliation verification baseline',
      },
    });
    expect(restored.status()).toBe(200);
  }
});

test('staff account switching clears scoped resources and keeps role separate from grants', async ({
  page,
}) => {
  await login(page, 'Rowan Vale');
  await navigate(page, 'Resource library');
  await expect(page.getByRole('heading', { name: 'No resources granted yet' })).toBeVisible();
  await page.getByRole('button', { name: /Project collection/ }).click();
  await expect(page.getByRole('heading', { name: 'Audience atlas', exact: true })).toBeVisible();
  const delayedPath =
    '**/organizations/20000000-0000-4000-8000-000000000001/projects/30000000-0000-4000-8000-000000000001/resources?*';
  let captured = false;
  let released = false;
  let lateResponseIds: string[] = [];
  let releaseResponse!: () => void;
  let settleResponse!: () => void;
  const held = new Promise<void>((resolve) => {
    releaseResponse = resolve;
  });
  const settled = new Promise<void>((resolve) => {
    settleResponse = resolve;
  });
  await page.route(delayedPath, async (route) => {
    const actual = await route.fetch();
    expect(actual.status()).toBe(200);
    const body = await actual.json();
    lateResponseIds = body.items.map((resource: { id: string }) => resource.id);
    expect(lateResponseIds).toContain('40000000-0000-4000-8000-000000000002');
    captured = true;
    await held;
    await route.fulfill({ response: actual });
    released = true;
    settleResponse();
  });
  await page.getByRole('searchbox').fill('Audience');
  await expect
    .poll(() => captured, { message: 'A real Cedar resource response is held in flight' })
    .toBe(true);
  await page.getByLabel('Organization', { exact: true }).selectOption({ label: 'Birch Labs' });
  await expect(page.getByLabel('Project', { exact: true })).toHaveValue(
    '30000000-0000-4000-8000-000000000003',
  );
  await navigate(page, 'Resource library');
  await expect(page.getByRole('heading', { name: 'No resources granted yet' })).toBeVisible();
  await page.getByRole('button', { name: /Project collection/ }).click();
  await expect(page.getByRole('heading', { name: 'Revenue compass', exact: true })).toBeVisible();
  releaseResponse();
  await settled;
  expect(released).toBe(true);
  await expect(page.getByRole('heading', { name: 'Audience atlas', exact: true })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Revenue compass', exact: true })).toBeVisible();
  await expect(page.getByRole('searchbox')).toHaveValue('');
  await page.unroute(delayedPath);
  await page.getByLabel('Organization', { exact: true }).selectOption({ label: 'Cedar Studio' });
  await navigate(page, 'Resource library');
  await expect(page.getByRole('heading', { name: 'No resources granted yet' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Revenue compass', exact: true })).toHaveCount(0);
  await expect(page.getByRole('searchbox')).toHaveValue('');
  await page.getByLabel('Organization', { exact: true }).selectOption({ label: 'Birch Labs' });
  await test.info().attach('delayed-tenant-response', {
    body: JSON.stringify({
      source: 'real Cedar API response',
      release: 'after Birch resource collection became visible',
      capturedResourceIds: lateResponseIds,
      lateResponseReleased: released,
      targetContents: 'Revenue compass only; no Cedar resource or previous search selection',
    }),
    contentType: 'application/json',
  });
  await writeBrowserEvidence('tenant-delay-evidence', {
    schemaVersion: 1,
    recordedAt: new Date().toISOString(),
    test: test.info().title,
    source: 'actual Cedar API response',
    captureBeforeSwitch: captured,
    releaseAfterBirchVisible: released,
    capturedResourceIds: lateResponseIds,
    departedContentsAbsent: true,
    departedSearchCleared: true,
    returnedScopeStartsWithExplicitGrants: true,
  });
  await navigate(page, 'Migration review');
  await expect(page.getByRole('heading', { name: 'Migration review', exact: true })).toBeVisible();
});

test('localized search, narrow layouts, keyboard navigation, and last manager protection', async ({
  page,
}) => {
  await page.goto('/');
  await expect(page.getByRole('link', { name: 'Sign in to your workspace' })).toBeVisible();
  await scanAccessibility(page, 'sign-in-entry');
  await login(page, 'Amelia Brooks');
  await navigate(page, 'Resource library');
  await page.getByLabel('Resource language', { exact: true }).selectOption('pt');
  await expect(page.getByRole('heading', { name: 'Pulso de mercado' })).toBeVisible();
  await page.getByRole('searchbox').fill('Pulso');
  await expect(page.locator('.resource-card')).toHaveCount(1);
  await page.getByRole('searchbox').fill('unavailable-query');
  await expect(page.getByRole('heading', { name: 'No resources match this search' })).toBeVisible();
  await navigate(page, 'Members & access');
  await page.getByRole('button', { name: 'Suspend Amelia Brooks', exact: true }).click();
  await page.keyboard.press('Tab');
  expect(
    await page.getByRole('dialog').evaluate((dialog) => dialog.contains(document.activeElement)),
  ).toBe(true);
  await page.getByRole('button', { name: 'Confirm suspension' }).click();
  await expect(page.getByRole('alert')).toContainText(/manager/i);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: 'Suspend Amelia Brooks', exact: true }),
  ).toBeFocused();
  test.setTimeout(360_000);
  for (const width of [375, 768, 1440]) {
    await page.setViewportSize({ width, height: 950 });
    const keyboard = new KeyboardJourney(page, width);
    const email = `keyboard-${width}-${crypto.randomUUID().slice(0, 8)}@example.test`;
    const recipient = page.getByRole('row').filter({ hasText: 'Jonah Reed' });
    await scanAccessibility(page, `members-${width}`);

    // Every operator action in these journeys uses browser keyboard events only.
    await keyboard.navigate('Overview');
    await expect(page.locator('.resource-preview')).toHaveCount(3);
    await scanAccessibility(page, `overview-${width}`);
    await keyboard.navigate('Resource library');
    await expect(page.locator('.resource-card')).toHaveCount(3);
    await expect(page.getByRole('button', { name: 'Grid view', pressed: true })).toBeVisible();
    await scanAccessibility(page, `resource-grid-${width}`);
    await keyboard.activate(page.getByRole('button', { name: 'List view', exact: true }));
    await expect(page.getByRole('button', { name: 'List view', pressed: true })).toBeVisible();
    await scanAccessibility(page, `resource-list-${width}`);
    await keyboard.type(page.getByRole('searchbox'), 'Market');
    await expect(page.locator('.resource-card')).toHaveCount(1);
    await keyboard.activate(page.getByRole('button', { name: 'Clear search', exact: true }));
    await expect(page.getByRole('searchbox')).toBeFocused();
    await expect(page.getByRole('searchbox')).toHaveValue('');
    await expect(page.locator('.resource-card')).toHaveCount(3);
    await keyboard.navigate('Audit activity');
    await expect(page.locator('.audit-event').first()).toBeVisible();
    await scanAccessibility(page, `audit-activity-${width}`);
    await keyboard.navigate('Invitations');
    await keyboard.startInvitationHistory();
    await scanAccessibility(page, `invitation-history-${width}`);
    await keyboard.activate(page.getByRole('button', { name: 'Create invitation', exact: true }));
    await keyboard.type(page.getByRole('textbox', { name: 'Recipient email' }), email);
    await keyboard.toggle(page.getByRole('checkbox', { name: /Market pulse/ }));
    await scanAccessibility(page, `invitation-selection-${width}`);
    await keyboard.activate(page.getByRole('button', { name: 'Review invitation', exact: true }));
    await expect(page.locator('.review-resources')).toContainText('Market pulse');
    await scanAccessibility(page, `invitation-review-${width}`);
    await keyboard.activate(page.getByRole('button', { name: 'Create verified invitation' }));
    await expect(page.getByRole('status').filter({ hasText: 'Invitation created.' })).toBeVisible();
    await keyboard.activate(
      page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }),
    );
    await expect(
      page.getByRole('button', { name: 'Create invitation', exact: true }),
    ).toBeFocused();
    await keyboard.findInvitation(email);
    await keyboard.activate(
      page.getByRole('button', { name: `Revoke invitation to ${email}`, exact: true }),
    );
    await keyboard.activate(
      page.getByRole('dialog').getByRole('button', { name: 'Revoke invitation', exact: true }),
    );
    await expect(page.getByRole('row').filter({ hasText: email })).toContainText('revoked');

    await keyboard.navigate('Members & access');
    await keyboard.activate(recipient.getByRole('button', { name: 'Manage access' }));
    const growth = page.getByRole('checkbox', { name: /Growth signals/ });
    await expect(growth).not.toBeChecked();
    await keyboard.toggle(growth);
    await keyboard.type(
      page.getByRole('textbox', { name: 'Reason for this change' }),
      `Keyboard verified growth assignment at ${width} pixels`,
    );
    await scanAccessibility(page, `grant-selection-${width}`);
    await keyboard.activate(page.getByRole('button', { name: 'Preview change' }));
    await expect(page.getByText('1 addition', { exact: true })).toBeVisible();
    await scanAccessibility(page, `grant-review-${width}`);
    await keyboard.activate(page.getByRole('button', { name: 'Confirm access change' }));
    await expect(page.getByRole('status').filter({ hasText: 'Access updated.' })).toBeVisible();
    await keyboard.activate(
      page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }),
    );
    await expect(recipient.getByRole('button', { name: 'Manage access' })).toBeFocused();

    // Restore the confirmed grant through the same reviewed keyboard path.
    await keyboard.activate(recipient.getByRole('button', { name: 'Manage access' }));
    await expect(growth).toBeChecked();
    await keyboard.toggle(growth);
    await keyboard.type(
      page.getByRole('textbox', { name: 'Reason for this change' }),
      `Complete keyboard verification at ${width} pixels`,
    );
    await keyboard.activate(page.getByRole('button', { name: 'Preview change' }));
    await expect(page.getByRole('button', { name: 'Confirm access change' })).toBeDisabled();
    await keyboard.toggle(
      page.getByRole('checkbox', { name: /I confirm removal of 1 resource grant/ }),
    );
    await keyboard.activate(page.getByRole('button', { name: 'Confirm access change' }));
    await expect(page.getByRole('status').filter({ hasText: 'Access updated.' })).toBeVisible();
    await keyboard.activate(
      page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }),
    );
    await keyboard.activate(recipient.getByRole('button', { name: 'Manage access' }));
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(recipient.getByRole('button', { name: 'Manage access' })).toBeFocused();
    await keyboard.attachEvidence();
  }
  await page.setViewportSize({ width: 320, height: 950 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await writeInteractionEvidence(page);
});

test('explicit panel fault injection leaves independent panels usable and supports recovery', async ({
  page,
}) => {
  await page.route('**/projects/*/resources?limit=100&view=granted&locale=en', (route) =>
    route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({
        error: {
          code: 'internal_error',
          message: 'Injected resource panel failure for browser resilience verification.',
          correlation_id: '00000000-0000-4000-8000-000000000999',
        },
      }),
    }),
  );
  await login(page, 'Amelia Brooks');
  await expect(page.getByRole('heading', { name: 'Good to see you, Amelia.' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Your resource collection' })).toBeVisible();
  await expect(page.getByLabel('Organization', { exact: true })).toHaveValue(
    '20000000-0000-4000-8000-000000000001',
  );
  await expect(page.getByLabel('Project', { exact: true })).toHaveValue(
    '30000000-0000-4000-8000-000000000001',
  );
  await expect(page.locator('.stat-card').nth(1).locator('strong')).toHaveText(/^[1-9]\d*$/);
  await expect(page.locator('.activity-preview .audit-event').first()).toBeVisible();
  await expect(page.locator('.resource-preview')).toHaveCount(0);
  await expect(page.getByRole('alert')).toContainText('Injected resource panel failure');
  await page.locator('.stat-card').nth(1).press('Enter');
  await expect(page.getByRole('row').filter({ hasText: 'Amelia Brooks' })).toBeVisible();
  await navigate(page, 'Overview');
  await expect(page.getByRole('alert')).toContainText('Injected resource panel failure');
  await page.unroute('**/projects/*/resources?limit=100&view=granted&locale=en');
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.locator('.resource-preview')).toHaveCount(3);
});

test('real competing grant command produces 412, preserves intent, and requires another review', async ({
  page,
}) => {
  await login(page, 'Amelia Brooks');
  const organization = '20000000-0000-4000-8000-000000000001';
  const path = `/api/v1/organizations/${organization}/memberships/50000000-0000-4000-8000-000000000002/projects/30000000-0000-4000-8000-000000000001/grants`;
  const session = await (await page.request.get('/api/v1/me')).json();
  const original = await verifiedRead(page, `${path}?limit=100`);
  const headers = { 'X-CSRF-Token': session.csrf_token, Origin: 'http://localhost:5187' };
  try {
    await navigate(page, 'Members & access');
    await page
      .getByRole('row')
      .filter({ hasText: 'Jonah Reed' })
      .getByRole('button', { name: 'Manage access' })
      .click();
    await page.getByRole('checkbox', { name: /Growth signals/ }).check();
    await page
      .getByRole('textbox', { name: 'Reason for this change' })
      .fill('Approved growth analysis assignment');
    const competing = await page.request.patch(path, {
      headers: {
        ...headers,
        'Idempotency-Key': crypto.randomUUID(),
        'If-Match': `"v${original.access_version}"`,
      },
      data: {
        add: ['40000000-0000-4000-8000-000000000002'],
        remove: [],
        reason: 'Concurrent audience research assignment',
      },
    });
    expect(competing.status()).toBe(200);
    await page.getByRole('button', { name: 'Preview change' }).click();
    await page.getByRole('button', { name: 'Confirm access change' }).click();
    await expect(page.getByRole('alert')).toContainText('Access changed');
    await page
      .getByRole('button', { name: 'Reload current access and review the preserved draft' })
      .click();
    await expect(page.getByRole('checkbox', { name: /Growth signals/ })).toBeChecked();
    await expect(page.getByRole('checkbox', { name: /Audience atlas/ })).toBeChecked();
    await page.getByRole('button', { name: 'Preview change' }).click();
    await expect(page.getByText('0 removals', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Confirm access change' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Access updated.' })).toBeVisible();
  } finally {
    const current = await verifiedRead(page, `${path}?limit=100`);
    const before = new Set<string>(
      original.items
        .filter((item: { state: string }) => item.state === 'active')
        .map((item: { resource_id: string }) => item.resource_id),
    );
    const after = new Set<string>(
      current.items
        .filter((item: { state: string }) => item.state === 'active')
        .map((item: { resource_id: string }) => item.resource_id),
    );
    const restored = await page.request.patch(path, {
      headers: {
        ...headers,
        'Idempotency-Key': crypto.randomUUID(),
        'If-Match': `"v${current.access_version}"`,
      },
      data: {
        add: [...before].filter((id) => !after.has(id)),
        remove: [...after].filter((id) => !before.has(id)),
        reason: 'Restore synthetic browser verification baseline',
      },
    });
    expect(restored.status()).toBe(200);
  }
});
