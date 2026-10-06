import { ArrowLeft, ArrowRight } from 'lucide-react';
import { Button } from './ui';

export function Pagination({
  page,
  hasNext,
  next,
  previous,
  busy = false,
  label = 'Results pages',
}: {
  page: number;
  hasNext: boolean;
  next: () => void;
  previous: () => void;
  busy?: boolean;
  label?: string;
}) {
  if (page === 1 && !hasNext) return null;
  return (
    <nav className="pagination" aria-label={label} aria-busy={busy || undefined}>
      <span role="status" aria-live="polite" aria-atomic="true">
        Page {page} · Up to 25 results
      </span>
      <div>
        <Button className="button-ghost" disabled={page === 1 || busy} onClick={previous}>
          <ArrowLeft size={15} />
          Previous
        </Button>
        <Button className="button-ghost" disabled={!hasNext || busy} onClick={next}>
          Next
          <ArrowRight size={15} />
        </Button>
      </div>
    </nav>
  );
}
