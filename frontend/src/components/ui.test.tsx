import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Button, ChoiceGroup, Dialog, SearchBox } from './ui';
import { Pagination } from './Pagination';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('workspace controls', () => {
  it('clears a controlled search, restores its input focus, and does not submit its enclosing form', () => {
    const submit = vi.fn();
    function SearchForm() {
      const [search, setSearch] = useState('Market');
      return (
        <form onSubmit={submit}>
          <SearchBox value={search} onChange={setSearch} placeholder="Search project resources…" />
          <Button>Inspect plan</Button>
        </form>
      );
    }
    render(<SearchForm />);
    const input = screen.getByRole('searchbox', { name: 'Search project resources…' });
    fireEvent.click(screen.getByRole('button', { name: 'Clear search' }));
    expect(input).toHaveValue('');
    expect(input).toHaveFocus();
    expect(screen.queryByRole('button', { name: 'Clear search' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Inspect plan' }));
    expect(submit).not.toHaveBeenCalled();
  });

  it('exposes the resource scope selection to assistive technology and updates it through native buttons', () => {
    function ScopeChoices() {
      const [scope, setScope] = useState<'granted' | 'entitled'>('granted');
      return (
        <ChoiceGroup
          label="Resource scope"
          value={scope}
          onChange={setScope}
          options={[
            { value: 'granted', label: 'My resources', detail: 'Explicit grants' },
            { value: 'entitled', label: 'Project collection', detail: 'Management view' },
          ]}
        />
      );
    }
    render(<ScopeChoices />);
    expect(screen.getByRole('group', { name: 'Resource scope' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /My resources/, pressed: true })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Project collection/ }));
    expect(
      screen.getByRole('button', { name: /Project collection/, pressed: true }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /My resources/, pressed: false }),
    ).toBeInTheDocument();
  });

  it('disables paging during a pending response while retaining the previous-page recovery control', () => {
    const next = vi.fn();
    const previous = vi.fn();
    const { rerender } = render(
      <Pagination page={2} hasNext busy next={next} previous={previous} label="Resource pages" />,
    );
    expect(screen.getByRole('navigation', { name: 'Resource pages' })).toHaveAttribute(
      'aria-busy',
      'true',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Previous' }));
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(next).not.toHaveBeenCalled();
    expect(previous).not.toHaveBeenCalled();
    rerender(
      <Pagination
        page={2}
        hasNext={false}
        next={next}
        previous={previous}
        label="Resource pages"
      />,
    );
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Previous' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Previous' }));
    expect(previous).toHaveBeenCalledOnce();
  });

  it('associates each dialog with its own title and description and restores trigger focus', () => {
    Object.defineProperties(HTMLDialogElement.prototype, {
      showModal: {
        configurable: true,
        value(this: HTMLDialogElement) {
          this.setAttribute('open', '');
        },
      },
      close: {
        configurable: true,
        value(this: HTMLDialogElement) {
          this.removeAttribute('open');
        },
      },
    });
    const trigger = document.createElement('button');
    document.body.append(trigger);
    trigger.focus();
    const { unmount } = render(
      <>
        <Dialog title="Review grants" subtitle="Cedar / Harbor" onClose={vi.fn()}>
          <p>Plan</p>
        </Dialog>
        <Dialog title="Review invitation" subtitle="Morgan" onClose={vi.fn()}>
          <p>Recipient</p>
        </Dialog>
      </>,
    );
    const grants = screen.getByRole('dialog', { name: 'Review grants' });
    const invitation = screen.getByRole('dialog', { name: 'Review invitation' });
    expect(grants).toHaveAccessibleDescription('Cedar / Harbor');
    expect(invitation).toHaveAccessibleDescription('Morgan');
    expect(grants.getAttribute('aria-labelledby')).not.toBe(
      invitation.getAttribute('aria-labelledby'),
    );
    unmount();
    expect(trigger).toHaveFocus();
    trigger.remove();
    Reflect.deleteProperty(HTMLDialogElement.prototype, 'showModal');
    Reflect.deleteProperty(HTMLDialogElement.prototype, 'close');
  });
});
