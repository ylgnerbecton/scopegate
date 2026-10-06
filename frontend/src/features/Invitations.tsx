import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRight,
  Check,
  Clock3,
  ExternalLink,
  Mail,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  X,
} from 'lucide-react';
import {
  Badge,
  Brand,
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
  CommandKeys,
  read,
  request,
  scopedPath,
  write,
  type MailMessage,
  type Schema,
  type Session,
} from '../lib/api';
import { usePagedQuery } from '../lib/queries';
import { displayDate, navigateWorkspace, scopeKey, type Scope } from '../lib/workspace';
import { EntitledChoices } from './Members';

export function Invitations({ scope, project }: { scope: Scope; project: Schema<'Project'> }) {
  const [create, setCreate] = useState(false);
  const invitations = usePagedQuery<Schema<'Invitation'>>(
    scopeKey(scope, 'invitation-page'),
    scopedPath(scope.organization, '/invitations'),
  );
  return (
    <>
      <PageHeading
        eyebrow="Workspace / Onboarding"
        title="Invitations"
        description="A verified identity, a clear resource plan, and a single-use invitation. No implicit permissions."
        action={
          <Button className="button-dark" onClick={() => setCreate(true)}>
            <Plus size={16} />
            Create invitation
          </Button>
        }
      />
      <section className="panel">
        <SectionHeading
          title="Invitation history"
          detail={`Explicit resource plans for ${project.name} and this organization`}
        />
        {invitations.isPending ? (
          <Loading label="Loading invitations" />
        ) : invitations.error ? (
          <ErrorPanel error={invitations.error} retry={() => void invitations.refetch()} />
        ) : invitations.data?.items.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Recipient</th>
                  <th>Invitation status</th>
                  <th>Delivery</th>
                  <th>Expires</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {invitations.data.items.map((invitation) => (
                  <InvitationRow key={invitation.id} invitation={invitation} scope={scope} />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="A thoughtful welcome starts here"
            detail="Create an invitation with an explicit resource plan. Acceptance never grants more than the plan you review."
            action={
              <Button className="button-dark" onClick={() => setCreate(true)}>
                <Mail size={16} />
                Invite your first member
              </Button>
            }
          />
        )}
        <Pagination
          page={invitations.page}
          hasNext={Boolean(invitations.data?.next_cursor)}
          next={invitations.next}
          previous={invitations.previous}
        />
      </section>
      <LocalMailbox scope={scope} />
      {create && (
        <CreateInvitation scope={scope} project={project} onClose={() => setCreate(false)} />
      )}
    </>
  );
}
function InvitationRow({ invitation, scope }: { invitation: Schema<'Invitation'>; scope: Scope }) {
  const [confirm, setConfirm] = useState(false);
  const keys = useRef(new CommandKeys());
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: (operation: 'resend' | 'revoke') => {
      const path = scopedPath(scope.organization, `/invitations/${invitation.id}/${operation}`);
      return write<Schema<'Invitation'>>(path, {}, keys.current.get(path, {}));
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['scope', scope.user, scope.organization] });
      keys.current.clear();
      setConfirm(false);
    },
  });
  const tone =
    invitation.state === 'accepted'
      ? 'green'
      : invitation.state === 'pending'
        ? 'amber'
        : 'neutral';
  return (
    <tr>
      <td>
        <div className="recipient-cell">
          <span className="recipient-icon">
            <Mail size={17} />
          </span>
          <div>
            <strong>{invitation.recipient_email}</strong>
            <small>Viewer invitation</small>
          </div>
        </div>
        {mutation.error && (
          <p className="row-error" role="alert">
            {mutation.error.message}
          </p>
        )}
      </td>
      <td>
        <Badge tone={tone}>{invitation.state}</Badge>
        {invitation.state === 'expired' && (
          <small className="status-explanation">Acceptance window closed</small>
        )}
      </td>
      <td>
        <span className={`delivery-label delivery-${invitation.delivery_state}`}>
          {invitation.delivery_state === 'delivered' ? <Check size={13} /> : <Clock3 size={13} />}
          {invitation.delivery_state}
        </span>
        {invitation.delivery_state === 'failed' && (
          <small className="status-explanation">
            {invitation.state === 'pending'
              ? 'Delivery attempts exhausted. Resend to issue a fresh link.'
              : 'Delivery is closed for this invitation.'}
          </small>
        )}
      </td>
      <td>
        <time dateTime={invitation.expires_at}>{displayDate(invitation.expires_at)}</time>
      </td>
      <td>
        <div className="row-actions">
          {invitation.state === 'pending' && (
            <>
              <button
                className="icon-button"
                aria-label={`Resend invitation to ${invitation.recipient_email}`}
                disabled={mutation.isPending}
                onClick={() => mutation.mutate('resend')}
              >
                <RefreshCw size={15} />
              </button>
              <button
                className="icon-button"
                aria-label={`Revoke invitation to ${invitation.recipient_email}`}
                disabled={mutation.isPending}
                onClick={() => setConfirm(true)}
              >
                <X size={17} />
              </button>
            </>
          )}
          {confirm && (
            <Dialog
              title="Revoke this invitation?"
              subtitle={invitation.recipient_email}
              onClose={() => setConfirm(false)}
            >
              <div className="dialog-body">
                <p>
                  The recipient will no longer be able to accept this invitation. Existing
                  memberships and grants are unchanged.
                </p>
                {mutation.error && <ErrorPanel error={mutation.error} />}
              </div>
              <div className="dialog-footer">
                <Button className="button-ghost" onClick={() => setConfirm(false)}>
                  Cancel
                </Button>
                <Button
                  className="button-danger"
                  pending={mutation.isPending}
                  onClick={() => mutation.mutate('revoke')}
                >
                  Revoke invitation
                </Button>
              </div>
            </Dialog>
          )}
        </div>
      </td>
    </tr>
  );
}
function CreateInvitation({
  scope,
  project,
  onClose,
}: {
  scope: Scope;
  project: Schema<'Project'>;
  onClose: () => void;
}) {
  const [email, setEmail] = useState('');
  const [expiry, setExpiry] = useState(72);
  const [selected, setSelected] = useState(new Set<string>());
  const [labels, setLabels] = useState(new Map<string, string>());
  const [review, setReview] = useState(false);
  const keys = useRef(new CommandKeys());
  const client = useQueryClient();
  const payload = {
    email: email.trim(),
    expires_in_hours: expiry,
    resources: [...selected].map((id) => ({ project_id: scope.project, resource_id: id })),
  };
  const mutation = useMutation({
    mutationFn: () => {
      const path = scopedPath(scope.organization, '/invitations');
      return write<Schema<'Invitation'>>(path, payload, keys.current.get(path, payload));
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['scope', scope.user, scope.organization] });
    },
  });
  const toggle = (id: string, title?: string) => {
    if (title) setLabels((current) => new Map(current).set(id, title));
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const valid =
    /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && selected.size > 0 && selected.size <= 100;
  return (
    <Dialog
      wide
      title="Invite a new member"
      subtitle={`${project.name} · viewer role · explicitly selected resources`}
      onClose={onClose}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (review) mutation.mutate();
          else setReview(true);
        }}
      >
        <div className="dialog-body">
          {mutation.isSuccess ? (
            <Notice>
              <span>
                <strong>Invitation created.</strong> Delivery is {mutation.data.delivery_state}.
                Membership and grants will be created only after verified acceptance.
              </span>
            </Notice>
          ) : review ? (
            <div className="invitation-review">
              <span className="review-icon">
                <Send size={26} />
              </span>
              <h3>A precise welcome for {email}</h3>
              <div className="detail-facts">
                <div>
                  <span>Project</span>
                  <strong>{project.name}</strong>
                </div>
                <div>
                  <span>Resource plan</span>
                  <strong>
                    {selected.size} explicit {selected.size === 1 ? 'grant' : 'grants'}
                  </strong>
                </div>
                <div>
                  <span>Expires in</span>
                  <strong>{expiry} hours</strong>
                </div>
                <div>
                  <span>Membership role</span>
                  <strong>Viewer</strong>
                </div>
              </div>
              <ul className="review-resources">
                {[...selected].map((id) => (
                  <li key={id}>
                    <Check size={15} />
                    {labels.get(id) || `Resource …${id.slice(-8)}`}
                  </li>
                ))}
              </ul>
              <Notice tone="amber">
                Only this reviewed resource plan is applied. A verified matching identity must
                accept the invitation.
              </Notice>
            </div>
          ) : (
            <>
              <div className="form-grid">
                <label className="field-label">
                  Recipient email
                  <input
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="name@example.test"
                    required
                    maxLength={254}
                    autoComplete="off"
                  />
                </label>
                <label className="field-label">
                  Invitation expiry
                  <select
                    value={expiry}
                    onChange={(event) => setExpiry(Number(event.target.value))}
                  >
                    <option value={24}>24 hours</option>
                    <option value={72}>72 hours</option>
                    <option value={168}>7 days</option>
                  </select>
                </label>
              </div>
              <div className="form-section-heading">
                <h3>Choose the resource plan</h3>
                <span>{selected.size} selected</span>
              </div>
              <EntitledChoices scope={scope} selected={selected} toggle={toggle} />
              <p className="form-help">
                Resources are entitled to {project.name}. Nothing outside this plan will be granted.
              </p>
            </>
          )}
          {mutation.error && <ErrorPanel error={mutation.error} />}
        </div>
        <div className="dialog-footer">
          <Button
            type="button"
            className="button-ghost"
            onClick={mutation.isSuccess ? onClose : review ? () => setReview(false) : onClose}
          >
            {mutation.isSuccess ? 'Close' : review ? 'Back to selection' : 'Cancel'}
          </Button>
          {!mutation.isSuccess && (
            <Button
              type="submit"
              className="button-dark"
              pending={mutation.isPending}
              disabled={!valid}
            >
              {review ? 'Create verified invitation' : 'Review invitation'}
              <ArrowRight size={15} />
            </Button>
          )}
        </div>
      </form>
    </Dialog>
  );
}

function LocalMailbox({ scope }: { scope: Scope }) {
  const messages = useQuery({
    queryKey: scopeKey(scope, 'local-mailbox'),
    queryFn: ({ signal }) =>
      read<{ items: MailMessage[] }>(scopedPath(scope.organization, '/mailbox'), signal),
    refetchInterval: 5_000,
    retry: false,
  });
  return (
    <section className="panel local-mailbox">
      <SectionHeading
        title="Local delivery inbox"
        detail="Protected messages from the local delivery adapter. Available only in this environment."
        action={
          <Button className="button-ghost" onClick={() => void messages.refetch()}>
            <RefreshCw size={14} />
            Refresh
          </Button>
        }
      />
      {messages.isPending ? (
        <Loading label="Checking local delivery" />
      ) : messages.error ? (
        <p className="muted-text">The local delivery inbox is unavailable in this environment.</p>
      ) : messages.data?.items.length ? (
        <div className="mailbox-list">
          {messages.data.items.map((message) => (
            <article key={message.id}>
              <span className="mailbox-icon">
                <Mail size={19} />
              </span>
              <div>
                <strong>{message.subject}</strong>
                <p>
                  To {message.recipient_email} <span className="middle-dot">·</span>
                  {displayDate(message.created_at)}
                </p>
              </div>
              <a className="button button-ghost" href={message.accept_url}>
                Open invitation
                <ExternalLink size={14} />
              </a>
            </article>
          ))}
        </div>
      ) : (
        <div className="mailbox-empty">
          <Mail size={21} />
          <p>
            Delivered invitations appear here. The outbox worker dispatches them asynchronously.
          </p>
        </div>
      )}
    </section>
  );
}

function invitationToken() {
  const token =
    new URLSearchParams(window.location.hash.slice(1)).get('token') ??
    new URLSearchParams(window.location.search).get('token');
  if (token) {
    sessionStorage.setItem('scopegate.invitation', token);
    window.history.replaceState({}, '', '/invitations/accept');
  }
  return token ?? sessionStorage.getItem('scopegate.invitation') ?? '';
}
export function InvitationAcceptance({
  session,
  loading,
}: {
  session?: Session;
  loading: boolean;
}) {
  const [token] = useState(invitationToken);
  const [completed, setCompleted] = useState(false);
  const [acceptedPlan, setAcceptedPlan] = useState<Schema<'InvitationPreview'> | null>(null);
  const keys = useRef(new CommandKeys());
  const client = useQueryClient();
  const preview = useQuery({
    queryKey: ['invitation-preview', session?.id],
    queryFn: () =>
      request<Schema<'InvitationPreview'>>('/api/v1/invitations/preview', {
        method: 'POST',
        body: JSON.stringify({ token }),
      }),
    enabled: Boolean(session && token && !completed),
    retry: false,
  });
  const accept = useMutation({
    mutationFn: () =>
      write<Schema<'Membership'>>(
        '/api/v1/invitations/accept',
        { token },
        keys.current.get('/api/v1/invitations/accept', { token }),
      ),
    onSuccess: () => {
      setAcceptedPlan(preview.data ?? null);
      setCompleted(true);
      sessionStorage.removeItem('scopegate.invitation');
      void client.invalidateQueries({ queryKey: ['session'] });
      void client.invalidateQueries({ queryKey: ['organizations'] });
    },
  });
  const changeAccount = async () => {
    await request('/api/v1/logout', { method: 'POST' });
    client.clear();
    window.location.assign('/auth/login?return_to=/invitations/accept');
  };
  const enterWorkspace = () => {
    const organization = accept.data!.organization_id;
    navigateWorkspace(organization, acceptedPlan?.resources[0]?.project_id ?? '', 'resources');
    window.location.reload();
  };
  return (
    <main className="acceptance-page">
      <Brand />
      <section className="acceptance-card">
        <span className="acceptance-icon">
          <Mail size={30} />
        </span>
        <p className="eyebrow">A thoughtful welcome</p>
        <h1>Your workspace invitation</h1>
        {accept.isSuccess ? (
          <>
            <Notice>
              Invitation accepted. Your membership and the exact reviewed resource grants are
              confirmed.
            </Notice>
            <Button className="button-dark" onClick={enterWorkspace}>
              Enter {acceptedPlan?.organization.name ?? 'your workspace'}
              <ArrowRight size={16} />
            </Button>
          </>
        ) : loading ? (
          <Loading label="Verifying your identity" />
        ) : !token ? (
          <Empty
            title="No invitation selected"
            detail="Open the single-use link from your invitation to review its organization and resource plan."
          />
        ) : !session ? (
          <>
            <p>
              Sign in with the verified email that received this invitation. You can review its
              resource plan before accepting.
            </p>
            <a className="button button-dark" href="/auth/login?return_to=/invitations/accept">
              Sign in to review
              <ArrowRight size={16} />
            </a>
          </>
        ) : preview.isPending ? (
          <Loading label="Reviewing the invitation" />
        ) : preview.error ? (
          <>
            <ErrorPanel error={preview.error} />
            <p className="form-help">
              Signed in as {session.email}. The invitation requires a recently verified, matching
              identity.
            </p>
            <Button className="button-ghost" onClick={() => void changeAccount()}>
              Change account or sign in again
              <ArrowRight size={15} />
            </Button>
          </>
        ) : preview.data ? (
          <>
            <p>
              You’re invited to join <strong>{preview.data.organization.name}</strong> as a viewer.
            </p>
            <div className="acceptance-identity">
              <ShieldCheck size={16} />
              <span>Verified recipient: {preview.data.recipient_email}</span>
            </div>
            <div className="accepted-resource-plan">
              <h2>Your explicit resource plan</h2>
              {preview.data.resources.map((resource) => (
                <div key={`${resource.project_id}:${resource.resource_id}`}>
                  <Check size={16} />
                  <span>
                    <strong>{resource.resource_title ?? resource.external_key}</strong>
                    <small>
                      {resource.project_name} · {resource.external_key}
                    </small>
                  </span>
                </div>
              ))}
            </div>
            <p className="form-help">
              Expires {displayDate(preview.data.expires_at)}. Accepting applies only this plan. It
              cannot reactivate a suspended membership.
            </p>
            {accept.error && <ErrorPanel error={accept.error} />}
            <Button
              className="button-dark"
              pending={accept.isPending}
              onClick={() => accept.mutate()}
            >
              Accept invitation
              <ArrowRight size={16} />
            </Button>
            <button className="acceptance-switch" onClick={() => void changeAccount()}>
              Signed in as {session.email} · Change account
            </button>
          </>
        ) : null}
      </section>
      <p className="acceptance-footer">
        <ShieldCheck size={14} />
        Verified identity. Explicit permission.
      </p>
    </main>
  );
}
