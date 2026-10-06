import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  CommandKeys,
  queryString,
  request,
  retryRead,
  scopedPath,
  setCsrfToken,
  write,
} from './api';
import { scopeKey } from './workspace';

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken('');
});

describe('command transport', () => {
  it('keeps an uncertain command key stable and distinguishes payload, route, and expected revision', () => {
    const keys = new CommandKeys();
    const body = { add: ['resource-a'], remove: [], reason: 'Approved scope' };
    const first = keys.get('/members/member-a/grants', body, 1);
    expect(keys.get('/members/member-a/grants', body, 1)).toBe(first);
    expect(keys.get('/members/member-a/grants', body, 2)).not.toBe(first);
    expect(keys.get('/members/member-b/grants', body, 1)).not.toBe(first);
    expect(keys.get('/members/member-a/grants', { ...body, remove: ['resource-b'] }, 1)).not.toBe(
      first,
    );
    keys.clear();
    expect(keys.get('/members/member-a/grants', body, 1)).not.toBe(first);
  });
  it('sends the current CSRF token, opaque command key, and quoted optimistic version', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ access_version: 2 }), { status: 200 }));
    vi.stubGlobal('fetch', fetch);
    setCsrfToken('session-csrf');
    await write(
      '/api/v1/organizations/a/memberships/b/projects/c/grants',
      { add: [], remove: ['r'], reason: 'Approved removal' },
      'fixed-command-key',
      'PATCH',
      1,
    );
    const options = fetch.mock.calls[0][1] as RequestInit;
    const headers = new Headers(options.headers);
    expect(headers.get('X-CSRF-Token')).toBe('session-csrf');
    expect(headers.get('Idempotency-Key')).toBe('fixed-command-key');
    expect(headers.get('If-Match')).toBe('"v1"');
    expect(options.credentials).toBe('same-origin');
  });
  it('preserves structured concurrency errors and correlation without pretending success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: 'access_version_conflict',
              message: 'Review current access.',
              correlation_id: 'request-reference',
            },
          }),
          { status: 412 },
        ),
      ),
    );
    await expect(request('/api/v1/resource')).rejects.toMatchObject({
      status: 412,
      code: 'access_version_conflict',
      correlationId: 'request-reference',
    });
  });
  it('does not convert a network interruption into a saved result', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(request('/api/v1/resource')).rejects.toMatchObject({
      status: 0,
      code: 'network_unavailable',
    });
  });
  it('keeps canceled tenant reads canceled rather than showing a stale failure', async () => {
    const aborted = new DOMException('Scope changed', 'AbortError');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(aborted));
    await expect(request('/api/v1/resource')).rejects.toBe(aborted);
  });
});
describe('scoped query boundaries', () => {
  it('distinguishes user, organization, project, and view cache identities', () => {
    const scope = { user: 'user-a', organization: 'org-a', project: 'project-a' };
    const first = scopeKey(scope, 'resources', 'granted');
    expect(scopeKey({ ...scope, organization: 'org-b' }, 'resources', 'granted')).not.toEqual(
      first,
    );
    expect(scopeKey({ ...scope, project: 'project-b' }, 'resources', 'granted')).not.toEqual(first);
    expect(scopeKey({ ...scope, user: 'user-b' }, 'resources', 'granted')).not.toEqual(first);
    expect(scopeKey(scope, 'resources', 'entitled')).not.toEqual(first);
  });
  it('encodes untrusted identifiers and scoped filters', () => {
    expect(scopedPath('../foreign')).toBe('/api/v1/organizations/..%2Fforeign');
    expect(queryString({ q: 'a&organization=other', limit: 25, cursor: undefined })).toBe(
      '?q=a%26organization%3Dother&limit=25',
    );
  });
  it('does not automatically retry authentication, version conflicts, or command failures', () => {
    expect(retryRead(0, new ApiError(401, 'session_required', 'Sign in'))).toBe(false);
    expect(retryRead(0, new ApiError(412, 'access_version_conflict', 'Review'))).toBe(false);
    expect(retryRead(0, new ApiError(503, 'temporarily_unavailable', 'Retry'))).toBe(true);
    expect(retryRead(1, new ApiError(503, 'temporarily_unavailable', 'Retry'))).toBe(false);
  });
});
