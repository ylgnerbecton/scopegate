import type { Schema } from './api';

export function activeGrantIds(items: Schema<'Grant'>[]) {
  return new Set(
    items.filter((grant) => grant.state === 'active').map((grant) => grant.resource_id),
  );
}

/** Rebase only the user's explicit additions/removals; preserve unrelated competing changes. */
export function rebaseGrantDraft(
  previous: Set<string>,
  desired: Set<string>,
  current: Set<string>,
) {
  const rebased = new Set(current);
  for (const id of desired) if (!previous.has(id)) rebased.add(id);
  for (const id of previous) if (!desired.has(id)) rebased.delete(id);
  return rebased;
}
