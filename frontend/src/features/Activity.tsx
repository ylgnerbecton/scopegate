import { useState } from 'react';
import {
  ArrowDownLeft,
  ArrowUpRight,
  Check,
  ChevronDown,
  ChevronRight,
  History,
  Mail,
  ShieldCheck,
  UserRound,
} from 'lucide-react';
import { Badge, Empty, ErrorPanel, Loading, PageHeading } from '../components/ui';
import { Pagination } from '../components/Pagination';
import { scopedPath, type Schema } from '../lib/api';
import { usePagedQuery } from '../lib/queries';
import { displayDate, humanize, scopeKey, type Scope } from '../lib/workspace';

export function Activity({ scope }: { scope: Scope }) {
  const [filter, setFilter] = useState('');
  return (
    <>
      <PageHeading
        eyebrow="Workspace / Accountability"
        title="Audit activity"
        description="A durable history of confirmed changes. Every action stays within its organization."
      />
      <div className="toolbar">
        <div className="toolbar-caption">
          <History size={18} />
          <span>Organization activity</span>
        </div>
        <label className="filter-select">
          <span className="sr-only">Action filter</span>
          <select value={filter} onChange={(event) => setFilter(event.target.value)}>
            <option value="">All actions</option>
            <option value="grants.updated">Grant changes</option>
            <option value="invitation.created">Invitations created</option>
            <option value="invitation.accepted">Invitations accepted</option>
            <option value="membership.suspended">Membership changes</option>
          </select>
          <ChevronDown size={15} />
        </label>
      </div>
      <ActivityPage key={filter} scope={scope} filter={filter} />
    </>
  );
}
function ActivityPage({ scope, filter }: { scope: Scope; filter: string }) {
  const events = usePagedQuery<Schema<'AuditEvent'>>(
    scopeKey(scope, 'audit'),
    scopedPath(scope.organization, '/audit-events'),
    { action: filter },
  );
  return (
    <section className="panel">
      {events.isPending ? (
        <Loading label="Loading audit events" />
      ) : events.error ? (
        <ErrorPanel error={events.error} retry={() => void events.refetch()} />
      ) : (
        <AuditList events={events.data?.items ?? []} />
      )}
      <Pagination
        page={events.page}
        hasNext={Boolean(events.data?.next_cursor)}
        next={events.next}
        previous={events.previous}
      />
    </section>
  );
}
export function AuditList({
  events,
  compact = false,
}: {
  events: Schema<'AuditEvent'>[];
  compact?: boolean;
}) {
  const [expanded, setExpanded] = useState('');
  if (!events.length)
    return (
      <Empty
        title="A clear history starts here"
        detail="Confirmed access changes and protected resource admissions will appear in this organization’s activity."
      />
    );
  return (
    <div className={`audit-list ${compact ? 'audit-list-compact' : ''}`}>
      {events.map((event) => {
        const Icon = event.action.includes('invitation')
          ? Mail
          : event.action.includes('grant')
            ? event.action.includes('revok')
              ? ArrowDownLeft
              : ArrowUpRight
            : event.action.includes('membership')
              ? UserRound
              : ShieldCheck;
        return (
          <article className="audit-event" key={event.id}>
            <span className="audit-icon">
              <Icon size={17} />
            </span>
            <div className="audit-body">
              <div className="audit-title">
                <strong>{humanize(event.action)}</strong>
                <Badge tone="green">
                  <Check size={11} />
                  Recorded
                </Badge>
              </div>
              <p>
                <span className="audit-actor" title={event.actor_key}>
                  {event.actor_display_name || `Account …${event.actor_key.slice(-8)}`}
                </span>
                <span className="middle-dot">·</span>
                {humanize(event.target_type)}{' '}
                <code title={event.target_id}>…{event.target_id.slice(-8)}</code>
              </p>
              {!compact && (
                <>
                  <button
                    className="event-details"
                    onClick={() => setExpanded(expanded === event.id ? '' : event.id)}
                    aria-expanded={expanded === event.id}
                  >
                    {expanded === event.id ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                    Change details
                  </button>
                  {expanded === event.id && (
                    <pre className="audit-details">
                      {JSON.stringify(
                        {
                          actor: event.actor_key,
                          correlation_id: event.correlation_id,
                          change: event.safe_change_summary ?? {},
                        },
                        null,
                        2,
                      )}
                    </pre>
                  )}
                </>
              )}
            </div>
            <time dateTime={event.created_at}>{displayDate(event.created_at)}</time>
          </article>
        );
      })}
    </div>
  );
}
