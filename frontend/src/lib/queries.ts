import { useState } from 'react';
import { hashKey, useQuery } from '@tanstack/react-query';
import { queryString, read } from './api';

export type Page<T> = { items: T[]; next_cursor: string | null };
export function usePagedQuery<T>(
  key: readonly unknown[],
  path: string,
  filters: Record<string, string | number | undefined> = {},
) {
  const identity = hashKey([...key, path, filters]);
  const [navigation, setNavigation] = useState<{
    identity: string;
    cursors: (string | undefined)[];
  }>({ identity, cursors: [undefined] });
  // A changed scope or filter starts at page one before any old cursor can be sent.
  if (navigation.identity !== identity) setNavigation({ identity, cursors: [undefined] });
  const cursors = navigation.identity === identity ? navigation.cursors : [undefined];
  const cursor = cursors[cursors.length - 1];
  const query = useQuery({
    queryKey: [...key, path, filters, cursor],
    queryFn: ({ signal }) =>
      read<Page<T>>(`${path}${queryString({ ...filters, limit: 25, cursor })}`, signal),
  });
  return {
    ...query,
    page: cursors.length,
    hasNext: Boolean(query.data?.next_cursor && !cursors.includes(query.data.next_cursor)),
    next: () => {
      const nextCursor = query.data?.next_cursor;
      if (!nextCursor || query.isFetching || cursors.includes(nextCursor)) return;
      setNavigation((current) => {
        const currentCursors = current.identity === identity ? current.cursors : [undefined];
        if (currentCursors[currentCursors.length - 1] !== cursor) return current;
        return { identity, cursors: [...currentCursors, nextCursor] };
      });
    },
    previous: () => {
      setNavigation((current) => {
        if (current.identity !== identity || current.cursors.length === 1) return current;
        if (current.cursors[current.cursors.length - 1] !== cursor) return current;
        return { identity, cursors: current.cursors.slice(0, -1) };
      });
    },
  };
}
