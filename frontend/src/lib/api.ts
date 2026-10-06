import type { components } from '../generated/api';

export type Schema<K extends keyof components['schemas']> = components['schemas'][K];
export type Session = Schema<'User'> & { csrf_token: string; memberships: Schema<'Membership'>[] };
export type MailMessage = {
  id: string;
  recipient_email: string;
  subject: string;
  accept_url: string;
  created_at: string;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public correlationId?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

let csrfToken = '';
export function setCsrfToken(token: string) {
  csrfToken = token;
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set('Accept', 'application/json');
  if (options.body) headers.set('Content-Type', 'application/json');
  if (options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrfToken);
  let response: Response;
  try {
    const deadline = AbortSignal.timeout(5_000);
    const signal = options.signal ? AbortSignal.any([options.signal, deadline]) : deadline;
    response = await fetch(path, { ...options, signal, headers, credentials: 'same-origin' });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(
      0,
      'network_unavailable',
      'The connection was interrupted. Your draft is preserved. Retry to confirm the result.',
    );
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as Schema<'Error'> | null;
    throw new ApiError(
      response.status,
      payload?.error?.code ?? 'request_failed',
      payload?.error?.message ?? 'This request could not be completed.',
      payload?.error?.correlation_id,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function scopedPath(organization: string, suffix = '') {
  return `/api/v1/organizations/${encodeURIComponent(organization)}${suffix}`;
}
export function queryString(values: Record<string, string | number | undefined>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values))
    if (value !== undefined && value !== '') query.set(key, String(value));
  return query.toString() ? `?${query}` : '';
}
export function read<T>(path: string, signal?: AbortSignal) {
  return request<T>(path, { signal });
}
export function write<T>(
  path: string,
  body: unknown,
  key: string,
  method = 'POST',
  version?: number,
) {
  return request<T>(path, {
    method,
    body: JSON.stringify(body),
    headers: {
      'Idempotency-Key': key,
      ...(version !== undefined ? { 'If-Match': `"v${version}"` } : {}),
    },
  });
}

/** Keep the same key for an uncertain command; a changed draft receives a new key. */
export class CommandKeys {
  private keys = new Map<string, string>();
  get(path: string, payload: unknown, version?: number) {
    const fingerprint = JSON.stringify([path, payload, version]);
    if (!this.keys.has(fingerprint)) this.keys.set(fingerprint, crypto.randomUUID());
    return this.keys.get(fingerprint)!;
  }
  clear() {
    this.keys.clear();
  }
}

export function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'This request could not be completed.';
}
export function retryRead(count: number, error: unknown) {
  return count < 1 && error instanceof ApiError && error.status >= 500;
}
