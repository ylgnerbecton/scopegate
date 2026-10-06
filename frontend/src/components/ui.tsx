import { useEffect, useId, useRef, type ReactNode } from 'react';
import {
  AlertCircle,
  ArrowRight,
  Check,
  LoaderCircle,
  RefreshCw,
  Search,
  X,
  ShieldCheck,
} from 'lucide-react';
import { ApiError, errorMessage } from '../lib/api';

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`brand ${compact ? 'brand-compact' : ''}`}>
      <span className="brand-mark" aria-hidden="true">
        <i />
        <i />
      </span>
      <span>
        scopegate<span className="brand-dot">.</span>
      </span>
    </div>
  );
}
export function Badge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode;
  tone?: 'neutral' | 'green' | 'amber' | 'red' | 'blue';
}) {
  return (
    <span className={`badge badge-${tone}`}>
      <span className="badge-dot" />
      {children}
    </span>
  );
}
export function Button({
  children,
  pending,
  className = '',
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { pending?: boolean }) {
  return (
    <button
      {...props}
      type={props.type ?? 'button'}
      disabled={props.disabled || pending}
      className={`button ${className}`}
      aria-busy={pending || undefined}
    >
      {pending ? <LoaderCircle size={16} className="spin" /> : null}
      {children}
    </button>
  );
}
export function ErrorPanel({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div className="error-panel" role="alert">
      <AlertCircle size={20} />
      <div>
        <strong>
          {error instanceof ApiError && error.status === 412
            ? 'Access changed while you were editing'
            : 'This panel is unavailable'}
        </strong>
        <p>{errorMessage(error)}</p>
        {error instanceof ApiError && error.correlationId && (
          <small>Reference: {error.correlationId}</small>
        )}
      </div>
      {retry && (
        <Button className="button-ghost" onClick={retry}>
          <RefreshCw size={15} />
          Retry
        </Button>
      )}
    </div>
  );
}
export function Loading({ label = 'Loading workspace' }: { label?: string }) {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle size={22} className="spin" />
      <span>{label}…</span>
    </div>
  );
}
export function Empty({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <ShieldCheck size={25} />
      </span>
      <h3>{title}</h3>
      <p>{detail}</p>
      {action}
    </div>
  );
}
export function SearchBox({
  value,
  onChange,
  placeholder = 'Search resources…',
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  return (
    <div className="search-box">
      <Search size={17} aria-hidden="true" />
      <label className="sr-only" htmlFor={id}>
        {placeholder}
      </label>
      <input
        id={id}
        ref={input}
        type="search"
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      {value && (
        <button
          type="button"
          className="search-clear"
          aria-label="Clear search"
          onClick={() => {
            onChange('');
            input.current?.focus();
          }}
        >
          <X size={15} aria-hidden="true" />
        </button>
      )}
    </div>
  );
}

export function ChoiceGroup<T extends string>({
  label,
  value,
  onChange,
  options,
  variant = 'tabs',
}: {
  label: string;
  value: T;
  onChange: (value: T) => void;
  options: readonly { value: T; label: string; detail?: string; icon?: ReactNode }[];
  variant?: 'tabs' | 'compact';
}) {
  return (
    <div
      className={variant === 'tabs' ? 'library-tabs' : 'display-switch'}
      role="group"
      aria-label={label}
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={value === option.value ? 'tab-active' : ''}
          aria-label={variant === 'compact' ? option.label : undefined}
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.icon && <span aria-hidden="true">{option.icon}</span>}
          {variant !== 'compact' && option.label}
          {option.detail && <span>{option.detail}</span>}
        </button>
      ))}
    </div>
  );
}
export function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="page-description">{description}</p>
      </div>
      {action}
    </div>
  );
}
export function Dialog({
  title,
  subtitle,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    const node = dialog.current;
    node?.showModal();
    document.body.dataset.scopeDraft = 'true';
    return () => {
      node?.close();
      delete document.body.dataset.scopeDraft;
      trigger?.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className={`dialog ${wide ? 'dialog-wide' : ''}`}
      aria-labelledby={titleId}
      aria-describedby={subtitle ? descriptionId : undefined}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className="dialog-heading">
        <div>
          <p className="eyebrow">Scoped change</p>
          <h2 id={titleId}>{title}</h2>
          {subtitle && <p id={descriptionId}>{subtitle}</p>}
        </div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="Close dialog">
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function Notice({
  children,
  tone = 'green',
}: {
  children: ReactNode;
  tone?: 'green' | 'amber';
}) {
  return (
    <div className={`notice notice-${tone}`} role="status">
      {tone === 'green' ? <Check size={17} /> : <AlertCircle size={17} />}
      <span>{children}</span>
    </div>
  );
}
export function SectionHeading({
  title,
  detail,
  action,
}: {
  title: string;
  detail?: string;
  action?: ReactNode;
}) {
  return (
    <div className="section-heading">
      <div>
        <h2>{title}</h2>
        {detail && <p>{detail}</p>}
      </div>
      {action}
    </div>
  );
}
export function TextLink({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button className="text-link" onClick={onClick}>
      {children}
      <ArrowRight size={15} />
    </button>
  );
}
