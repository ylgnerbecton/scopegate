import { ArrowLeft, ArrowRight } from 'lucide-react';
import { Button } from './ui';

export function Pagination({
  page,
  hasNext,
  next,
  previous,
}: {
  page: number;
  hasNext: boolean;
  next: () => void;
  previous: () => void;
}) {
  if (page === 1 && !hasNext) return null;
  return (
    <div className="pagination">
      <span>Page {page} · bounded to 25 records</span>
      <div>
        <Button className="button-ghost" disabled={page === 1} onClick={previous}>
          <ArrowLeft size={15} />
          Previous
        </Button>
        <Button className="button-ghost" disabled={!hasNext} onClick={next}>
          Next
          <ArrowRight size={15} />
        </Button>
      </div>
    </div>
  );
}
