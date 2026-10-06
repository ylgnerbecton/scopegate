import { useQuery } from '@tanstack/react-query';
import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  Mail,
  ShieldCheck,
  Users,
  GitBranch,
} from 'lucide-react';
import {
  Badge,
  Button,
  ErrorPanel,
  Loading,
  PageHeading,
  SectionHeading,
  TextLink,
} from '../components/ui';
import { ResourceVisual } from '../components/ResourceVisual';
import { read, scopedPath, type Schema, type Session } from '../lib/api';
import { navigateWorkspace, scopeKey, type Scope } from '../lib/workspace';
import { AuditList } from './Activity';

type OverviewProps = {
  scope: Scope;
  session: Session;
  organization: Schema<'Organization'>;
  project: Schema<'Project'>;
  isManager: boolean;
};
export function Overview({ scope, session, organization, project, isManager }: OverviewProps) {
  const resources = useQuery({
    queryKey: scopeKey(scope, 'resources', 'granted'),
    queryFn: ({ signal }) =>
      read<Schema<'ResourcePage'>>(
        scopedPath(
          scope.organization,
          `/projects/${scope.project}/resources?limit=100&view=granted&locale=en`,
        ),
        signal,
      ),
  });
  const members = useQuery({
    queryKey: scopeKey(scope, 'members'),
    queryFn: ({ signal }) =>
      read<Schema<'MembershipPage'>>(
        scopedPath(scope.organization, '/memberships?limit=100'),
        signal,
      ),
    enabled: isManager,
  });
  const invitations = useQuery({
    queryKey: scopeKey(scope, 'invitations'),
    queryFn: ({ signal }) =>
      read<Schema<'InvitationPage'>>(
        scopedPath(scope.organization, '/invitations?limit=100'),
        signal,
      ),
    enabled: isManager,
  });
  const audit = useQuery({
    queryKey: scopeKey(scope, 'recent-activity'),
    queryFn: ({ signal }) =>
      read<Schema<'AuditEventPage'>>(
        scopedPath(scope.organization, '/audit-events?limit=5'),
        signal,
      ),
    enabled: isManager,
  });
  const go = (view: 'resources' | 'members' | 'invitations' | 'activity') =>
    navigateWorkspace(scope.organization, scope.project, view);
  const membership = session.memberships.find((item) => item.organization_id === organization.id);
  return (
    <>
      <PageHeading
        eyebrow={`${organization.name} / ${project.name}`}
        title={`Good to see you, ${(session.display_name ?? 'there').split(' ')[0]}.`}
        description="A clear picture of your workspace. Every resource, every person, every permission."
        action={
          <Badge tone="green">
            {membership?.kind === 'staff' ? 'Time-limited staff access' : 'Active membership'}
          </Badge>
        }
      />
      <section className="overview-hero">
        <div className="hero-copy">
          <span className="hero-pill">
            <ShieldCheck size={14} />
            Purposeful permissions
          </span>
          <h2>
            Access that makes
            <br />
            sense at every level.
          </h2>
          <p>Keep {project.name} moving with the right people and precisely scoped resources.</p>
          <Button className="button-lime" onClick={() => go('resources')}>
            Explore your resources
            <ArrowRight size={16} />
          </Button>
        </div>
        <div
          className="access-map"
          aria-label="Access requires membership, entitlement, and an explicit grant"
        >
          <div className="map-line map-line-one" />
          <div className="map-line map-line-two" />
          <div className="map-node map-organization">
            <span className="node-icon">
              <Users size={19} />
            </span>
            <strong>{organization.name}</strong>
            <small>Active membership</small>
            <Check size={15} className="map-check" />
          </div>
          <div className="map-node map-project">
            <span className="node-icon">
              <GitBranch size={19} />
            </span>
            <strong>{project.name}</strong>
            <small>Project entitlement</small>
            <Check size={15} className="map-check" />
          </div>
          <div className="map-node map-resource">
            <span className="node-icon">
              <BookOpen size={19} />
            </span>
            <strong>Published resources</strong>
            <small>Explicit individual grant</small>
            <Check size={15} className="map-check" />
          </div>
          <span className="map-caption">Three checks. One clear boundary.</span>
        </div>
      </section>
      <section className="stats-grid" aria-label="Workspace summary">
        <Stat
          title="Your available resources"
          value={resources.data?.items.length}
          icon={<BookOpen size={20} />}
          detail="Explicitly granted in this project"
          boundary={resources.data?.next_cursor ? 'First page of granted resources' : undefined}
          pending={resources.isPending}
          error={resources.error}
          onClick={() => go('resources')}
        />
        {isManager && (
          <Stat
            title="Active members"
            value={members.data?.items.filter((item) => item.status === 'active').length}
            icon={<Users size={20} />}
            detail="Within this organization"
            boundary={
              members.data?.next_cursor ? 'Counted within the first membership page' : undefined
            }
            pending={members.isPending}
            error={members.error}
            onClick={() => go('members')}
          />
        )}
        {isManager && (
          <Stat
            title="Pending invitations"
            value={invitations.data?.items.filter((item) => item.state === 'pending').length}
            icon={<Mail size={20} />}
            detail="Waiting for verified acceptance"
            boundary={
              invitations.data?.next_cursor ? 'Counted within the first invitation page' : undefined
            }
            pending={invitations.isPending}
            error={invitations.error}
            onClick={() => go('invitations')}
          />
        )}
      </section>
      <div className="overview-bottom">
        <section className="panel">
          <SectionHeading
            title="Your resource collection"
            detail={`Ready to use in ${project.name}`}
            action={<TextLink onClick={() => go('resources')}>View library</TextLink>}
          />
          {resources.isPending ? (
            <Loading label="Loading resources" />
          ) : resources.error ? (
            <ErrorPanel error={resources.error} retry={() => void resources.refetch()} />
          ) : resources.data?.items.length ? (
            <div className="resource-preview-grid">
              {resources.data.items.slice(0, 3).map((resource) => (
                <button
                  className="resource-preview"
                  key={resource.id}
                  onClick={() => go('resources')}
                >
                  <ResourceVisual className="resource-art" resourceKey={resource.external_key} />
                  <span className="preview-content">
                    <small>{resource.tags?.[0] ?? 'Resource'}</small>
                    <strong>{resource.title ?? resource.external_key}</strong>
                    <span>
                      Open in library
                      <ArrowUpRight size={14} />
                    </span>
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <div className="collection-empty">
              <BookOpen size={24} />
              <h3>Your collection is ready for its first resource.</h3>
              <p>An access manager can grant resources for your project.</p>
            </div>
          )}
        </section>
        <section className="panel boundary-panel">
          <span className="boundary-icon">
            <ShieldCheck size={24} />
          </span>
          <p className="eyebrow">Your access boundary</p>
          <h2>Clarity is built in.</h2>
          <p>
            Being a member gives you a place in the workspace. Each resource still needs its own
            explicit grant.
          </p>
          <ul>
            <li>
              <Check size={15} />
              Organization-specific membership
            </li>
            <li>
              <Check size={15} />
              Project-specific entitlement
            </li>
            <li>
              <Check size={15} />
              Resource-specific permission
            </li>
          </ul>
          {membership?.expires_at && (
            <div className="staff-expiry">
              Staff access expires{' '}
              {new Date(membership.expires_at).toLocaleDateString('en', {
                month: 'short',
                day: 'numeric',
                year: 'numeric',
              })}
              .
            </div>
          )}
        </section>
      </div>
      {isManager && (
        <section className="panel activity-preview">
          <SectionHeading
            title="Recent activity"
            detail="Confirmed changes within this organization"
            action={<TextLink onClick={() => go('activity')}>View all activity</TextLink>}
          />
          {audit.isPending ? (
            <Loading label="Loading activity" />
          ) : audit.error ? (
            <ErrorPanel error={audit.error} retry={() => void audit.refetch()} />
          ) : (
            <AuditList events={audit.data?.items ?? []} compact />
          )}
        </section>
      )}
    </>
  );
}

function Stat({
  title,
  value,
  icon,
  detail,
  pending,
  error,
  onClick,
  boundary,
}: {
  title: string;
  value?: number;
  icon: React.ReactNode;
  detail: string;
  pending: boolean;
  error: unknown;
  onClick: () => void;
  boundary?: string;
}) {
  return (
    <button className="stat-card" onClick={onClick}>
      <span className="stat-top">
        <span>{title}</span>
        {icon}
      </span>
      <strong>{pending ? '—' : error ? 'Unavailable' : (value ?? 0)}</strong>
      {!pending && !error && boundary && (
        <span className="stat-boundary">{boundary} · More available</span>
      )}
      <span className="stat-detail">
        {detail}
        <ArrowUpRight size={14} />
      </span>
    </button>
  );
}
