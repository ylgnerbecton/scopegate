import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRight,
  Check,
  Download,
  FileCheck2,
  GitCompareArrows,
  Info,
  ListChecks,
  ShieldAlert,
  Workflow,
} from 'lucide-react';
import {
  Badge,
  Button,
  Dialog,
  Empty,
  ErrorPanel,
  Loading,
  Notice,
  PageHeading,
  SectionHeading,
} from '../components/ui';
import { Pagination } from '../components/Pagination';
import {
  ApiError,
  CommandKeys,
  queryString,
  read,
  scopedPath,
  write,
  type Schema,
  type Session,
} from '../lib/api';
import { usePagedQuery } from '../lib/queries';
import { humanize, scopeKey, type Scope } from '../lib/workspace';

export function Migration({ scope, session }: { scope: Scope; session: Session }) {
  const runs = useQuery({
    queryKey: scopeKey(scope, 'migration-runs'),
    queryFn: ({ signal }) =>
      read<Schema<'MigrationRunPage'>>(
        scopedPath(scope.organization, '/migration-runs?limit=100'),
        signal,
      ),
  });
  const [selected, setSelected] = useState('');
  const run = runs.data?.items.find((item) => item.id === selected) ?? runs.data?.items[0];
  return (
    <>
      <PageHeading
        eyebrow="Operations / Reconciliation"
        title="Migration review"
        description="Compare, investigate, and record explicit decisions. A reviewed dry run does not switch live access."
        action={
          <Badge tone="blue">
            <Workflow size={12} />
            Reviewer workspace
          </Badge>
        }
      />
      {runs.isPending ? (
        <Loading label="Loading migration runs" />
      ) : runs.error ? (
        <ErrorPanel error={runs.error} retry={() => void runs.refetch()} />
      ) : !run ? (
        <Empty
          title="No migration runs to review"
          detail="Run the profiling and comparison commands against an approved snapshot. Their versioned evidence will appear here."
        />
      ) : (
        <>
          <section className="migration-banner">
            <span className="migration-banner-icon">
              <GitCompareArrows size={26} />
            </span>
            <div>
              <p className="eyebrow">Explicit review before transition</p>
              <h2>Resolve the exceptions. Preserve the boundary.</h2>
              <p>Only a separately authorized, fenced CLI operation can perform cutover.</p>
            </div>
            <Badge tone="amber">{humanize(run.state)}</Badge>
          </section>
          <div className="migration-toolbar">
            <label className="field-label">
              Selected run
              <select value={run.id} onChange={(event) => setSelected(event.target.value)}>
                {runs.data?.items.map((item) => (
                  <option value={item.id} key={item.id}>
                    {item.id.slice(0, 8)} · {item.state}
                  </option>
                ))}
              </select>
            </label>
            <div className="snapshot-label">
              <span>Source snapshot</span>
              <code>{run.snapshot_hash.slice(0, 16)}…</code>
            </div>
            <ManifestDownload scope={scope} run={run} />
          </div>
          <section className="migration-stats">
            <MigrationStat
              title="Unresolved records"
              value={run.unresolved_count}
              icon={<ListChecks size={20} />}
              warning={run.unresolved_count > 0}
              detail="Explicit owner and decision required"
            />
            <MigrationStat
              title="Unreviewed gains"
              value={run.unreviewed_gain_count}
              icon={<ShieldAlert size={20} />}
              warning={run.unreviewed_gain_count > 0}
              detail="Potentially broader resource access"
            />
            <MigrationStat
              title="Unreviewed losses"
              value={run.unreviewed_loss_count}
              icon={<GitCompareArrows size={20} />}
              warning={run.unreviewed_loss_count > 0}
              detail="Potentially lost approved access"
            />
          </section>
          <MigrationLedger key={run.id} scope={scope} run={run} session={session} />
          <div className="inline-guidance">
            <Info size={17} />
            <p>
              Import counts are not proof of access parity. Unresolved blocking records keep the
              organization out of cutover.
            </p>
          </div>
        </>
      )}
    </>
  );
}
function MigrationStat({
  title,
  value,
  icon,
  detail,
  warning,
}: {
  title: string;
  value: number;
  icon: React.ReactNode;
  detail: string;
  warning: boolean;
}) {
  return (
    <div className={`migration-stat ${warning ? 'migration-stat-warning' : ''}`}>
      <span>
        {title}
        {icon}
      </span>
      <strong>{value}</strong>
      <p>{detail}</p>
    </div>
  );
}
function MigrationLedger({
  scope,
  run,
  session,
}: {
  scope: Scope;
  run: Schema<'MigrationRun'>;
  session: Session;
}) {
  const items = usePagedQuery<Schema<'LedgerEntry'>>(
    scopeKey(scope, 'migration-ledger', run.id),
    scopedPath(scope.organization, `/migration-runs/${run.id}/items`),
  );
  const [selected, setSelected] = useState<Schema<'LedgerEntry'> | null>(null);
  return (
    <section className="panel">
      <SectionHeading
        title="Reconciliation ledger"
        detail="Versioned decisions attached to source records. No automatic default mapping."
      />
      {items.isPending ? (
        <Loading label="Loading ledger items" />
      ) : items.error ? (
        <ErrorPanel error={items.error} retry={() => void items.refetch()} />
      ) : !items.data?.items.length ? (
        <Empty
          title="No ledger records in this run"
          detail="A reconciliation ledger is produced by profiling and backfill. Import counts alone do not authorize a transition."
        />
      ) : (
        <div className="ledger-list">
          {items.data.items.map((item) => (
            <article className="ledger-item" key={item.id}>
              <span
                className={`ledger-icon ${item.outcome === 'review_required' ? 'ledger-warning' : ''}`}
              >
                {item.outcome === 'review_required' ? (
                  <ShieldAlert size={20} />
                ) : (
                  <FileCheck2 size={20} />
                )}
              </span>
              <div className="ledger-content">
                <div>
                  <h3>{humanize(item.source_kind)}</h3>
                  <Badge
                    tone={
                      item.outcome === 'review_required'
                        ? 'amber'
                        : item.outcome === 'rejected'
                          ? 'red'
                          : 'green'
                    }
                  >
                    {humanize(item.outcome)}
                  </Badge>
                </div>
                <p>
                  Source <code>{item.source_key}</code>
                  <span className="middle-dot">·</span>Review v{item.review_version}
                </p>
                {item.decision_reason && <p className="decision-reason">{item.decision_reason}</p>}
                <small>
                  {item.assigned_owner_user_id
                    ? `Assigned owner ${item.assigned_owner_user_id === session.id ? session.display_name : `…${item.assigned_owner_user_id.slice(-8)}`}`
                    : 'No owner assigned'}
                  {item.target_id ? ` · Target ${item.target_id.slice(0, 16)}` : ''}
                </small>
              </div>
              <Button className="button-ghost" onClick={() => setSelected(item)}>
                Review decision
                <ArrowRight size={14} />
              </Button>
            </article>
          ))}
        </div>
      )}
      <Pagination
        page={items.page}
        hasNext={Boolean(items.data?.next_cursor)}
        next={items.next}
        previous={items.previous}
      />
      {selected && (
        <LedgerResolution
          scope={scope}
          run={run}
          item={selected}
          session={session}
          onClose={() => setSelected(null)}
        />
      )}
    </section>
  );
}
function LedgerResolution({
  scope,
  run,
  item,
  session,
  onClose,
}: {
  scope: Scope;
  run: Schema<'MigrationRun'>;
  item: Schema<'LedgerEntry'>;
  session: Session;
  onClose: () => void;
}) {
  const [outcome, setOutcome] = useState<Schema<'LedgerResolution'>['outcome']>(item.outcome);
  const [reason, setReason] = useState(item.decision_reason ?? '');
  const [targetKind, setTargetKind] = useState(item.target_kind ?? '');
  const [target, setTarget] = useState(item.target_id ?? '');
  const [owner, setOwner] = useState(item.assigned_owner_user_id === session.id);
  const [version, setVersion] = useState(item.review_version);
  const [latest, setLatest] = useState<Schema<'LedgerEntry'> | null>(null);
  const [reviewedConflict, setReviewedConflict] = useState(false);
  const client = useQueryClient();
  const keys = useRef(new CommandKeys());
  const payload: Schema<'LedgerResolution'> = {
    outcome,
    decision_reason: reason,
    target_kind: targetKind || null,
    target_id: target || null,
    assigned_owner_user_id: owner ? session.id : (item.assigned_owner_user_id ?? null),
  };
  const mutation = useMutation({
    mutationFn: () => {
      const path = scopedPath(scope.organization, `/migration-runs/${run.id}/items/${item.id}`);
      return write<Schema<'LedgerEntry'>>(
        path,
        payload,
        keys.current.get(path, payload, version),
        'PATCH',
        version,
      );
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['scope', scope.user, scope.organization] });
    },
  });
  const reload = useMutation({
    mutationFn: async () => {
      let cursor: string | undefined;
      let total = 0;
      do {
        const page = await read<Schema<'LedgerEntryPage'>>(
          scopedPath(
            scope.organization,
            `/migration-runs/${run.id}/items${queryString({ limit: 100, cursor })}`,
          ),
        );
        const current = page.items.find((entry) => entry.id === item.id);
        if (current) return current;
        total += page.items.length;
        if (total >= 10_000)
          throw new Error(
            'This record exceeds the browser review limit. Reopen the scoped ledger to continue.',
          );
        cursor = page.next_cursor ?? undefined;
      } while (cursor);
      throw new Error('This record is no longer present in the selected migration run.');
    },
    onSuccess: (current) => {
      setLatest(current);
      setVersion(current.review_version);
      setReviewedConflict(false);
      mutation.reset();
    },
  });
  return (
    <Dialog
      title="Record a reconciliation decision"
      subtitle={`${item.source_kind} / ${item.source_key} · review v${version}`}
      onClose={onClose}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <div className="dialog-body">
          <Notice tone="amber">
            This decision records reviewed evidence. It does not grant access or perform cutover.
          </Notice>
          <label className="field-label">
            Decision
            <select
              value={outcome}
              onChange={(event) =>
                setOutcome(event.target.value as Schema<'LedgerResolution'>['outcome'])
              }
            >
              <option value="review_required">Keep review required</option>
              <option value="mapped">Mapped to an explicit target</option>
              <option value="approved_change">Approved change</option>
              <option value="retained">Retain source record</option>
              <option value="rejected">Reject mapping</option>
            </select>
          </label>
          <div className="form-grid">
            <label className="field-label">
              Target kind
              <input
                value={targetKind}
                onChange={(event) => setTargetKind(event.target.value)}
                placeholder="membership, resource, report…"
                maxLength={100}
              />
            </label>
            <label className="field-label">
              Target identifier
              <input
                value={target}
                onChange={(event) => setTarget(event.target.value)}
                placeholder="Stable identifier, when applicable"
                maxLength={200}
              />
            </label>
          </div>
          <label className="field-label">
            Evidence and decision reason
            <textarea
              rows={4}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Record the reviewed evidence, decision owner, and expected access effect…"
              required
              minLength={3}
              maxLength={1000}
            />
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={owner}
              onChange={(event) => setOwner(event.target.checked)}
            />
            Assign this record to me ({session.display_name})
          </label>
          {mutation.error && <ErrorPanel error={mutation.error} />}
          {mutation.error instanceof ApiError && mutation.error.status === 412 && (
            <Button
              type="button"
              className="button-ghost"
              pending={reload.isPending}
              onClick={() => reload.mutate()}
            >
              Load competing decision and preserve my draft
            </Button>
          )}
          {reload.error && <ErrorPanel error={reload.error} />}
          {latest && (
            <div className="conflict-review">
              <Notice tone="amber">
                <span>
                  <strong>
                    Current decision: {humanize(latest.outcome)} · v{latest.review_version}
                  </strong>
                  <br />
                  {latest.decision_reason || 'No decision reason recorded.'}
                  <br />
                  Your draft is preserved. Review the current decision before recording a
                  replacement.
                </span>
              </Notice>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={reviewedConflict}
                  onChange={(event) => setReviewedConflict(event.target.checked)}
                />
                I reviewed the competing decision and intend to replace it
              </label>
            </div>
          )}
          {mutation.isSuccess && (
            <Notice>
              Decision recorded at review v{mutation.data.review_version}. Comparison must be rerun
              before transition readiness is assessed.
            </Notice>
          )}
        </div>
        <div className="dialog-footer">
          <Button type="button" className="button-ghost" onClick={onClose}>
            Close
          </Button>
          <Button
            type="submit"
            className="button-dark"
            pending={mutation.isPending}
            disabled={
              reason.trim().length < 3 || mutation.isSuccess || Boolean(latest && !reviewedConflict)
            }
          >
            <Check size={15} />
            Record reviewed decision
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
function ManifestDownload({ scope, run }: { scope: Scope; run: Schema<'MigrationRun'> }) {
  const exportManifest = useMutation({
    mutationFn: async () => {
      const decisions: Schema<'MigrationDecision'>[] = [];
      let cursor: string | undefined;
      do {
        const page = await read<Schema<'MigrationDecisionPage'>>(
          scopedPath(
            scope.organization,
            `/migration-runs/${run.id}/manifest${queryString({ limit: 100, cursor })}`,
          ),
        );
        decisions.push(...page.items);
        cursor = page.next_cursor ?? undefined;
        if (decisions.length > 10_000)
          throw new Error(
            'This manifest exceeds the browser export limit. Use the restricted migration CLI for a bounded export.',
          );
      } while (cursor);
      const blob = new Blob(
        [
          JSON.stringify(
            {
              run_id: run.id,
              snapshot_hash: run.snapshot_hash,
              baseline_manifest_hash: run.baseline_manifest_hash,
              target_manifest_hash: run.target_manifest_hash,
              decisions,
            },
            null,
            2,
          ),
        ],
        { type: 'application/json' },
      );
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `scopegate-manifest-${run.id.slice(0, 8)}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    },
  });
  return (
    <div className="manifest-download">
      <Button
        className="button-ghost"
        pending={exportManifest.isPending}
        onClick={() => exportManifest.mutate()}
      >
        <Download size={15} />
        Export decision manifest
      </Button>
      {exportManifest.error && (
        <p className="row-error" role="alert">
          {exportManifest.error.message}
        </p>
      )}
    </div>
  );
}
