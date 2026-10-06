import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRight,
  ChevronDown,
  MoreHorizontal,
  Plus,
  ShieldCheck,
  SlidersHorizontal,
  UserRound,
  Users,
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
  SearchBox,
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
} from '../lib/api';
import { usePagedQuery } from '../lib/queries';
import { activeGrantIds, rebaseGrantDraft } from '../lib/grants';
import { initials, navigateWorkspace, scopeKey, type Scope } from '../lib/workspace';

type Member = Schema<'Membership'> & { display_name?: string | null; email?: string };
type Snapshot = { items: Schema<'Grant'>[]; access_version: number };

export function Members({
  scope,
  organization,
  project,
}: {
  scope: Scope;
  organization: Schema<'Organization'>;
  project: Schema<'Project'>;
}) {
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  return (
    <>
      <PageHeading
        eyebrow="Workspace / People"
        title="Members & access"
        description="Give each person the resources they need. Every grant is specific to the selected project."
        action={
          <Button
            className="button-dark"
            onClick={() => navigateWorkspace(scope.organization, scope.project, 'invitations')}
          >
            <Plus size={16} />
            Invite a member
          </Button>
        }
      />
      <div className="toolbar">
        <SearchBox
          value={search}
          onChange={setSearch}
          placeholder="Find a member by name or email…"
        />
        <label className="filter-select">
          <Users size={15} />
          <span className="sr-only">Membership status</span>
          <select value={filter} onChange={(event) => setFilter(event.target.value)}>
            <option value="all">All members</option>
            <option value="active">Active members</option>
            <option value="suspended">Suspended members</option>
          </select>
          <ChevronDown size={14} />
        </label>
      </div>
      <MemberPage
        scope={scope}
        search={search}
        filter={filter}
        organization={organization}
        project={project}
      />
    </>
  );
}
function MemberPage({
  scope,
  search,
  filter,
  organization,
  project,
}: {
  scope: Scope;
  search: string;
  filter: string;
  organization: Schema<'Organization'>;
  project: Schema<'Project'>;
}) {
  const members = usePagedQuery<Member>(
    scopeKey(scope, 'membership-page'),
    scopedPath(scope.organization, '/memberships'),
  );
  const [editor, setEditor] = useState<Member | null>(null);
  const [stateTarget, setStateTarget] = useState<Member | null>(null);
  const items =
    members.data?.items.filter(
      (member) =>
        (filter === 'all' || member.status === filter) &&
        `${member.display_name ?? ''} ${member.email ?? ''} ${member.user_id}`
          .toLowerCase()
          .includes(search.toLowerCase()),
    ) ?? [];
  return (
    <>
      <section className="panel members-panel">
        <div className="table-caption">
          <span>
            {organization.name}
            <small>{items.length} members on this page</small>
          </span>
          <Badge tone="neutral">
            <ShieldCheck size={12} />
            Project: {project.name}
          </Badge>
        </div>
        {members.isPending ? (
          <Loading label="Loading members" />
        ) : members.error ? (
          <ErrorPanel error={members.error} retry={() => void members.refetch()} />
        ) : !items.length ? (
          <Empty
            title="No members match these filters"
            detail="Change your search or status filter. Results are scoped to this organization and the current page."
          />
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Member</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Membership</th>
                  <th>Access</th>
                  <th>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((member) => (
                  <tr key={member.id}>
                    <td>
                      <div className="person-cell">
                        <span className="avatar avatar-light">
                          {initials(member.display_name ?? member.email)}
                        </span>
                        <div>
                          <strong>
                            {member.display_name ??
                              member.email ??
                              `Member ${member.user_id.slice(0, 8)}`}
                          </strong>
                          <small>{member.email ?? member.user_id.slice(0, 8)}</small>
                        </div>
                      </div>
                    </td>
                    <td>
                      <span
                        className={`role-label ${member.role === 'access_manager' ? 'role-manager' : ''}`}
                      >
                        {member.role === 'access_manager' ? (
                          <ShieldCheck size={13} />
                        ) : (
                          <UserRound size={13} />
                        )}
                        {member.role === 'access_manager' ? 'Access manager' : 'Viewer'}
                      </span>
                    </td>
                    <td>
                      <Badge tone={member.status === 'active' ? 'green' : 'neutral'}>
                        {member.status}
                      </Badge>
                    </td>
                    <td>
                      <span className="membership-kind">
                        {member.kind === 'staff' ? 'Staff · time-limited' : 'Customer'}
                      </span>
                      {member.expires_at && (
                        <small className="expiry-date">
                          Until{' '}
                          {new Date(member.expires_at).toLocaleDateString('en', {
                            month: 'short',
                            day: 'numeric',
                          })}
                        </small>
                      )}
                    </td>
                    <td>
                      <button className="manage-access" onClick={() => setEditor(member)}>
                        <SlidersHorizontal size={14} />
                        Manage access
                        <ArrowRight size={13} />
                      </button>
                    </td>
                    <td>
                      <button
                        className="icon-button"
                        aria-label={`${member.status === 'active' ? 'Suspend' : 'Reactivate'} ${member.display_name ?? member.email ?? 'member'}`}
                        onClick={() => setStateTarget(member)}
                      >
                        <MoreHorizontal size={18} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pagination
          page={members.page}
          hasNext={members.hasNext}
          next={members.next}
          previous={members.previous}
          busy={members.isFetching}
          label="Member pages"
        />
      </section>
      <div className="inline-guidance">
        <ShieldCheck size={17} />
        <p>
          Management authority and resource access are separate. Managers still need individual
          grants to open resources.
        </p>
      </div>
      {editor && (
        <GrantEditor
          scope={scope}
          member={editor}
          project={project}
          organization={organization}
          onClose={() => setEditor(null)}
        />
      )}
      {stateTarget && (
        <MembershipStateDialog
          scope={scope}
          member={stateTarget}
          onClose={() => setStateTarget(null)}
        />
      )}
    </>
  );
}

async function grantSnapshot(
  scope: Scope,
  membership: string,
  signal?: AbortSignal,
): Promise<Snapshot> {
  const path = scopedPath(
    scope.organization,
    `/memberships/${membership}/projects/${scope.project}/grants`,
  );
  const items: Schema<'Grant'>[] = [];
  let cursor: string | undefined;
  let version: number | undefined;
  do {
    const page = await read<Schema<'GrantPage'>>(
      `${path}${queryString({ cursor, limit: 100 })}`,
      signal,
    );
    if (version !== undefined && page.access_version !== version)
      throw new ApiError(
        412,
        'access_version_conflict',
        'Access changed while loading. Refresh to use one consistent grant revision.',
      );
    version = page.access_version;
    items.push(...page.items);
    cursor = page.next_cursor ?? undefined;
    if (items.length > 10_000)
      throw new ApiError(
        422,
        'editor_limit',
        'This grant inventory exceeds the interactive editor limit. Use a bounded operational change.',
      );
  } while (cursor);
  return { items, access_version: version! };
}

function GrantEditor({
  scope,
  member,
  organization,
  project,
  onClose,
}: {
  scope: Scope;
  member: Member;
  organization: Schema<'Organization'>;
  project: Schema<'Project'>;
  onClose: () => void;
}) {
  const snapshot = useQuery({
    queryKey: scopeKey(scope, 'grant-snapshot', member.id),
    queryFn: ({ signal }) => grantSnapshot(scope, member.id, signal),
    staleTime: 0,
  });
  return (
    <Dialog
      wide
      title={`Access for ${member.display_name ?? member.email ?? 'this member'}`}
      subtitle={`${organization.name} / ${project.name} · changes affect only this membership and project`}
      onClose={onClose}
    >
      {snapshot.isPending || !snapshot.isFetchedAfterMount ? (
        <Loading label="Loading current grants" />
      ) : snapshot.error ? (
        <div className="dialog-body">
          <ErrorPanel error={snapshot.error} retry={() => void snapshot.refetch()} />
        </div>
      ) : (
        <GrantForm scope={scope} member={member} initial={snapshot.data!} onClose={onClose} />
      )}
    </Dialog>
  );
}

function GrantForm({
  scope,
  member,
  initial,
  onClose,
}: {
  scope: Scope;
  member: Member;
  initial: Snapshot;
  onClose: () => void;
}) {
  const [baseline, setBaseline] = useState(initial);
  const [selected, setSelected] = useState(
    () =>
      new Set(
        initial.items.filter((grant) => grant.state === 'active').map((grant) => grant.resource_id),
      ),
  );
  const [search, setSearch] = useState('');
  const [reason, setReason] = useState('');
  const [review, setReview] = useState(false);
  const [confirmedRemovals, setConfirmedRemovals] = useState(false);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const client = useQueryClient();
  const keys = useRef(new CommandKeys());
  const previous = new Set(
    baseline.items.filter((grant) => grant.state === 'active').map((grant) => grant.resource_id),
  );
  const add = [...selected].filter((id) => !previous.has(id));
  const remove = [...previous].filter((id) => !selected.has(id));
  const body = { add, remove, reason };
  const path = scopedPath(
    scope.organization,
    `/memberships/${member.id}/projects/${scope.project}/grants`,
  );
  const commit = useMutation({
    mutationFn: () =>
      write<Schema<'GrantResult'>>(
        path,
        body,
        keys.current.get(path, body, baseline.access_version),
        'PATCH',
        baseline.access_version,
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['scope', scope.user, scope.organization] });
      keys.current.clear();
    },
  });
  const refresh = useMutation({
    mutationFn: () => grantSnapshot(scope, member.id),
    onSuccess: (snapshot) => {
      setBaseline(snapshot);
      setSelected((desired) => rebaseGrantDraft(previous, desired, activeGrantIds(snapshot.items)));
      setReview(false);
      setConfirmedRemovals(false);
      commit.reset();
    },
  });
  const toggle = (id: string, title?: string) => {
    if (title) setLabels((current) => ({ ...current, [id]: title }));
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setReview(false);
    setConfirmedRemovals(false);
  };
  return (
    <>
      <div className="dialog-body">
        <div className="editor-summary">
          <span>
            <ShieldCheck size={16} />
            Current access revision <strong>v{baseline.access_version}</strong>
          </span>
          <Badge tone="neutral">
            {previous.size} active {previous.size === 1 ? 'grant' : 'grants'}
          </Badge>
        </div>
        {commit.isSuccess ? (
          <Notice>
            Access updated. Revision v{commit.data.access_version} is confirmed, with{' '}
            {commit.data.changed_grants.length} changed grants.
          </Notice>
        ) : (
          <>
            {!review ? (
              <>
                <SearchBox
                  value={search}
                  onChange={setSearch}
                  placeholder="Search project resources…"
                />
                <EntitledChoices
                  key={search}
                  scope={scope}
                  search={search}
                  selected={selected}
                  toggle={toggle}
                />
                <label className="field-label">
                  Reason for this change
                  <textarea
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    maxLength={500}
                    placeholder="Describe the approved project assignment…"
                    rows={2}
                  />
                </label>
                <p className="form-help">
                  This is a scoped difference. Resources outside the current selection are
                  preserved.
                </p>
              </>
            ) : (
              <div className="diff-preview">
                <h3>Review the exact change</h3>
                <div className="diff-columns">
                  <div className="diff-add">
                    <span>
                      {add.length} {add.length === 1 ? 'addition' : 'additions'}
                    </span>
                    {add.length ? (
                      add.map((id) => <span key={id}>{labels[id] ?? id.slice(0, 8)}</span>)
                    ) : (
                      <p>No resources added</p>
                    )}
                  </div>
                  <div className="diff-remove">
                    <span>
                      {remove.length} {remove.length === 1 ? 'removal' : 'removals'}
                    </span>
                    {remove.length ? (
                      remove.map((id) => <span key={id}>{labels[id] ?? id.slice(0, 8)}</span>)
                    ) : (
                      <p>No resources removed</p>
                    )}
                  </div>
                </div>
                <p>
                  {previous.size - remove.length} current{' '}
                  {previous.size - remove.length === 1 ? 'grant remains' : 'grants remain'}{' '}
                  unchanged. Reason: {reason}
                </p>
                {remove.length > 0 && (
                  <label className="checkbox-label destructive-confirm">
                    <input
                      type="checkbox"
                      checked={confirmedRemovals}
                      onChange={(event) => setConfirmedRemovals(event.target.checked)}
                    />
                    I confirm removal of {remove.length} resource{' '}
                    {remove.length === 1 ? 'grant' : 'grants'} in this project.
                  </label>
                )}
              </div>
            )}
            {commit.error && (
              <>
                <ErrorPanel error={commit.error} />
                {commit.error instanceof ApiError && commit.error.status === 412 && (
                  <Button
                    className="button-ghost"
                    pending={refresh.isPending}
                    onClick={() => refresh.mutate()}
                  >
                    Reload current access and review the preserved draft
                  </Button>
                )}
              </>
            )}
            {refresh.error && <ErrorPanel error={refresh.error} />}
          </>
        )}
      </div>
      <div className="dialog-footer">
        <span className="draft-count">
          {add.length + remove.length} proposed{' '}
          {add.length + remove.length === 1 ? 'change' : 'changes'}
        </span>
        <div>
          <Button
            className="button-ghost"
            onClick={commit.isSuccess ? onClose : review ? () => setReview(false) : onClose}
          >
            {commit.isSuccess ? 'Close' : review ? 'Back to selection' : 'Cancel'}
          </Button>
          {!commit.isSuccess && (
            <Button
              className="button-dark"
              pending={commit.isPending}
              disabled={
                add.length + remove.length === 0 ||
                reason.trim().length < 3 ||
                add.length > 100 ||
                remove.length > 100 ||
                (review && remove.length > 0 && !confirmedRemovals)
              }
              onClick={() => (review ? commit.mutate() : setReview(true))}
            >
              {review ? 'Confirm access change' : 'Preview change'}
              <ArrowRight size={15} />
            </Button>
          )}
        </div>
      </div>
    </>
  );
}

export function EntitledChoices({
  scope,
  search = '',
  selected,
  toggle,
}: {
  scope: Scope;
  search?: string;
  selected: Set<string>;
  toggle: (id: string, title?: string) => void;
}) {
  const resources = usePagedQuery<Schema<'Resource'>>(
    scopeKey(scope, 'entitled-choices'),
    scopedPath(scope.organization, `/projects/${scope.project}/resources`),
    { view: 'entitled', locale: 'en', q: search },
  );
  return (
    <div className="entitled-choices">
      {resources.isPending ? (
        <Loading label="Loading entitled resources" />
      ) : resources.error ? (
        <ErrorPanel error={resources.error} retry={() => void resources.refetch()} />
      ) : resources.data?.items.length ? (
        resources.data.items.map((resource) => (
          <label className="resource-choice" key={resource.id}>
            <input
              type="checkbox"
              checked={selected.has(resource.id)}
              disabled={resource.status !== 'published'}
              onChange={() => toggle(resource.id, resource.title ?? resource.external_key)}
            />
            <span className="choice-icon">
              <ShieldCheck size={17} />
            </span>
            <span>
              <strong>{resource.title ?? resource.external_key}</strong>
              <small>
                {resource.external_key} · {resource.status}
              </small>
            </span>
            <span className="choice-status">
              {selected.has(resource.id) ? 'Selected' : 'Available'}
            </span>
          </label>
        ))
      ) : (
        <Empty
          title={
            search
              ? 'No entitled resources match this search'
              : 'No entitled resources on this page'
          }
          detail={
            search
              ? 'Change the search to inspect other resources. Your selected plan is preserved.'
              : resources.page > 1
                ? 'Return to the previous page to inspect the current collection. Your selected plan is preserved.'
                : 'Project entitlements must be assigned before a manager can create an individual grant.'
          }
        />
      )}
      <Pagination
        page={resources.page}
        hasNext={resources.hasNext}
        next={resources.next}
        previous={resources.previous}
        busy={resources.isFetching}
        label="Entitled resource pages"
      />
    </div>
  );
}

function MembershipStateDialog({
  scope,
  member,
  onClose,
}: {
  scope: Scope;
  member: Member;
  onClose: () => void;
}) {
  const status = member.status === 'active' ? 'suspended' : 'active';
  const keys = useRef(new CommandKeys());
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => {
      const path = scopedPath(scope.organization, `/memberships/${member.id}`);
      return write<Schema<'Membership'>>(
        path,
        { status },
        keys.current.get(path, { status }, member.access_version),
        'PATCH',
        member.access_version,
      );
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['scope', scope.user, scope.organization] });
      void client.invalidateQueries({ queryKey: ['session'] });
    },
  });
  return (
    <Dialog
      title={`${status === 'suspended' ? 'Suspend' : 'Reactivate'} this membership?`}
      subtitle={member.display_name ?? member.email ?? member.user_id}
      onClose={onClose}
    >
      <div className="dialog-body">
        <p>
          {status === 'suspended'
            ? 'Future resource admissions for this organization will be denied after suspension commits. Access in other organizations remains separate.'
            : 'Reactivation restores membership eligibility. It does not create grants or restore grants independently revoked.'}
        </p>
        <Notice tone="amber">
          At least one active customer access manager must remain. Staff memberships never satisfy
          this requirement.
        </Notice>
        {mutation.error && <ErrorPanel error={mutation.error} />}
        {mutation.isSuccess && <Notice>Membership state confirmed: {mutation.data.status}.</Notice>}
      </div>
      <div className="dialog-footer">
        <Button className="button-ghost" onClick={onClose}>
          Close
        </Button>
        <Button
          className={status === 'suspended' ? 'button-danger' : 'button-dark'}
          pending={mutation.isPending}
          disabled={mutation.isSuccess}
          onClick={() => mutation.mutate()}
        >
          {status === 'suspended' ? 'Confirm suspension' : 'Confirm reactivation'}
        </Button>
      </div>
    </Dialog>
  );
}
