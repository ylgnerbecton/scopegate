import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, read, type Schema } from '../lib/api';
import { Resources } from './Resources';

vi.mock('../lib/api', async (original) => ({
  ...(await original<typeof import('../lib/api')>()),
  read: vi.fn(),
}));

const resource: Schema<'Resource'> = {
  id: 'resource-1',
  external_key: 'CL_DEMO',
  catalog_version: 1,
  status: 'published',
  title: 'Market pulse',
  description: null,
  fallback_used: false,
};
const project: Schema<'Project'> = {
  id: 'harbor',
  organization_id: 'cedar',
  name: 'Harbor',
  status: 'active',
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderResources() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <Resources
        scope={{ user: 'amelia', organization: 'cedar', project: 'harbor' }}
        project={project}
        isManager
      />
    </QueryClientProvider>,
  );
}

describe('resource panel recovery', () => {
  it.each(['empty', 'failed'] as const)(
    'keeps Previous reachable after a %s later page',
    async (outcome) => {
      vi.mocked(read).mockImplementation(async (path) => {
        if (path.includes('cursor=second')) {
          if (outcome === 'failed')
            throw new ApiError(503, 'temporarily_unavailable', 'Retry this panel.');
          return { items: [], next_cursor: null };
        }
        return { items: [resource], next_cursor: 'second' };
      });
      renderResources();
      await screen.findByRole('heading', { name: 'Market pulse' });
      expect(
        screen.queryByText('Published resource available within this project’s access boundary.'),
      ).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
      if (outcome === 'failed') await screen.findByRole('alert');
      else await screen.findByRole('heading', { name: 'This page has no resources' });
      const pages = screen.getByRole('navigation', { name: 'Resource pages' });
      expect(pages).toHaveTextContent('Page 2 ·');
      expect(within(pages).getByRole('button', { name: 'Previous' })).toBeEnabled();
      fireEvent.click(within(pages).getByRole('button', { name: 'Previous' }));
      await screen.findByRole('heading', { name: 'Market pulse' });
      expect(screen.getByRole('navigation', { name: 'Resource pages' })).toHaveTextContent(
        'Page 1 ·',
      );
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    },
  );

  it('distinguishes missing entitlements from missing personal grants and offers a search reset', async () => {
    vi.mocked(read).mockResolvedValue({ items: [], next_cursor: null });
    renderResources();
    await screen.findByRole('heading', { name: 'No resources granted yet' });
    fireEvent.click(screen.getByRole('button', { name: /Project collection/ }));
    await screen.findByRole('heading', { name: 'No resources entitled to this project' });
    const input = screen.getByRole('searchbox');
    fireEvent.change(input, { target: { value: 'unmatched' } });
    await screen.findByRole('heading', { name: 'No resources match this search' });
    fireEvent.click(screen.getByRole('button', { name: 'Reset search' }));
    await waitFor(() => expect(input).toHaveValue(''));
    await screen.findByRole('heading', { name: 'No resources entitled to this project' });
  });
});
