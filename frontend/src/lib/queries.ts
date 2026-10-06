import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { queryString, read } from './api';

export type Page<T> = { items: T[]; next_cursor: string | null };
export function usePagedQuery<T>(
  key: readonly unknown[],
  path: string,
  filters: Record<string, string | number | undefined> = {},
) {
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined]);
  const cursor = cursors[cursors.length - 1];
  const query = useQuery({
    queryKey: [...key, filters, cursor],
    queryFn: ({ signal }) =>
      read<Page<T>>(`${path}${queryString({ ...filters, limit: 25, cursor })}`, signal),
  });
  return {
    ...query,
    page: cursors.length,
    next: () => {
      if (query.data?.next_cursor) setCursors([...cursors, query.data.next_cursor]);
    },
    previous: () => setCursors(cursors.slice(0, -1)),
  };
}
