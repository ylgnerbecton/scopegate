import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { read } from './api';
import { usePagedQuery } from './queries';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  read: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

describe('bounded cursor navigation', () => {
  it('keeps page one valid and advances once when Next is activated twice before rendering', async () => {
    vi.mocked(read).mockImplementation(async (path) =>
      path.includes('cursor=second')
        ? { items: ['second item'], next_cursor: null }
        : { items: ['first item'], next_cursor: 'second' },
    );
    const { result } = renderHook(
      () => usePagedQuery<string>(['scope', 'user', 'org'], '/members'),
      { wrapper: wrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    act(() => result.current.previous());
    expect(result.current.page).toBe(1);
    act(() => {
      result.current.next();
      result.current.next();
    });
    await waitFor(() => expect(result.current.data?.items).toEqual(['second item']));
    expect(result.current.page).toBe(2);
    expect(vi.mocked(read).mock.calls.map(([path]) => path)).toEqual([
      '/members?limit=25',
      '/members?limit=25&cursor=second',
    ]);
  });

  it('does not send a previous scope or filter cursor to a changed query', async () => {
    vi.mocked(read).mockImplementation(async (path) => ({ items: [path], next_cursor: 'next' }));
    const { result, rerender } = renderHook(
      ({ organization, search }) =>
        usePagedQuery<string>(
          ['scope', 'user', organization],
          `/organizations/${organization}/resources`,
          { q: search },
        ),
      { wrapper: wrapper(), initialProps: { organization: 'cedar', search: '' } },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    act(() => result.current.next());
    await waitFor(() => expect(result.current.data?.items[0]).toContain('cursor=next'));
    rerender({ organization: 'birch', search: 'growth' });
    expect(result.current.page).toBe(1);
    await waitFor(() =>
      expect(result.current.data?.items).toEqual([
        '/organizations/birch/resources?q=growth&limit=25',
      ]),
    );
    expect(vi.mocked(read).mock.calls.at(-1)?.[0]).not.toContain('cursor=');
    act(() => result.current.next());
    await waitFor(() => expect(result.current.data?.items[0]).toContain('cursor=next'));
    rerender({ organization: 'birch', search: 'market' });
    expect(result.current.page).toBe(1);
    await waitFor(() =>
      expect(result.current.data?.items).toEqual([
        '/organizations/birch/resources?q=market&limit=25',
      ]),
    );
    rerender({ organization: 'cedar', search: '' });
    expect(result.current.page).toBe(1);
    await waitFor(() =>
      expect(result.current.data?.items).toEqual(['/organizations/cedar/resources?limit=25']),
    );
  });

  it('ignores a late response from the departed organization', async () => {
    let resolveOld!: (value: unknown) => void;
    vi.mocked(read).mockImplementation((path) =>
      path.startsWith('/cedar')
        ? new Promise((resolve) => {
            resolveOld = resolve;
          })
        : Promise.resolve({ items: ['Birch resource'], next_cursor: null }),
    );
    const { result, rerender } = renderHook(
      ({ organization }) =>
        usePagedQuery<string>(['scope', 'user', organization], `/${organization}/resources`),
      { wrapper: wrapper(), initialProps: { organization: 'cedar' } },
    );
    await waitFor(() => expect(vi.mocked(read)).toHaveBeenCalledOnce());
    rerender({ organization: 'birch' });
    await waitFor(() => expect(result.current.data?.items).toEqual(['Birch resource']));
    await act(async () => resolveOld({ items: ['Cedar resource'], next_cursor: 'cedar-page' }));
    expect(result.current.data?.items).toEqual(['Birch resource']);
    expect(result.current.page).toBe(1);
  });

  it('can return from an empty later page without losing the first-page cursor', async () => {
    vi.mocked(read).mockImplementation(async (path) =>
      path.includes('cursor=second')
        ? { items: [], next_cursor: null }
        : { items: ['first item'], next_cursor: 'second' },
    );
    const { result } = renderHook(
      () => usePagedQuery<string>(['scope', 'user', 'org'], '/resources'),
      { wrapper: wrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    act(() => result.current.next());
    await waitFor(() => expect(result.current.data?.items).toEqual([]));
    expect(result.current.page).toBe(2);
    act(() => result.current.previous());
    await waitFor(() => expect(result.current.data?.items).toEqual(['first item']));
    expect(result.current.page).toBe(1);
  });

  it('keeps the page for equivalent filter objects and rejects a repeated cursor', async () => {
    vi.mocked(read).mockResolvedValue({ items: ['resource'], next_cursor: 'same' });
    const { result, rerender } = renderHook(
      ({ filters }) => usePagedQuery<string>(['scope', 'user', 'org'], '/resources', filters),
      { wrapper: wrapper(), initialProps: { filters: { locale: 'en', view: 'granted' } } },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    act(() => result.current.next());
    await waitFor(() => expect(result.current.isFetching).toBe(false));
    expect(result.current.page).toBe(2);
    rerender({ filters: { view: 'granted', locale: 'en' } });
    expect(result.current.page).toBe(2);
    act(() => result.current.next());
    expect(result.current.page).toBe(2);
    expect(result.current.hasNext).toBe(false);
    expect(read).toHaveBeenCalledTimes(2);
  });
});
