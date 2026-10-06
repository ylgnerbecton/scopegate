import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRight,
  BookOpen,
  ChevronDown,
  CircleHelp,
  Command,
  FolderClosed,
  LayoutDashboard,
  LogOut,
  Mail,
  Menu,
  Shield,
  ShieldCheck,
  Users,
  Workflow,
  X,
  History,
} from 'lucide-react';
import { Badge, Brand, Empty, ErrorPanel, Loading } from './components/ui';
import {
  ApiError,
  read,
  request,
  setCsrfToken,
  scopedPath,
  type Schema,
  type Session,
} from './lib/api';
import {
  initials,
  navigateWorkspace,
  routeFromLocation,
  type Scope,
  type View,
} from './lib/workspace';
import { Overview } from './features/Overview';
import { Resources } from './features/Resources';
import { Members } from './features/Members';
import { Invitations, InvitationAcceptance } from './features/Invitations';
import { Activity } from './features/Activity';
import { Migration } from './features/Migration';

const navigation = [
  { view: 'overview', title: 'Overview', icon: LayoutDashboard },
  { view: 'resources', title: 'Resource library', icon: BookOpen },
  { view: 'members', title: 'Members & access', icon: Users, manager: true },
  { view: 'invitations', title: 'Invitations', icon: Mail, manager: true },
  { view: 'activity', title: 'Audit activity', icon: History, manager: true },
  { view: 'migration', title: 'Migration review', icon: Workflow, reviewer: true },
] as const;

function SignIn({ unavailable }: { unavailable?: unknown }) {
  return (
    <main className="sign-in">
      <section className="sign-in-copy">
        <Brand />
        <div>
          <p className="eyebrow">Clarity at every boundary</p>
          <h1>
            The right access.
            <br />
            In the right hands.
          </h1>
          <p>
            Bring your people, projects, and resources into one clear workspace. Every permission is
            explicit. Every change has a history.
          </p>
          <a className="button button-dark" href="/auth/login?return_to=/workspace">
            Sign in to your workspace
            <ArrowRight size={18} />
          </a>
          {Boolean(unavailable) && <ErrorPanel error={unavailable} />}
        </div>
        <p className="sign-in-footer">
          Access, with clarity. <span>Scopegate</span>
        </p>
      </section>
      <aside className="sign-in-visual" aria-label="Scopegate access principles">
        <div className="visual-grid" />
        <span className="visual-pill">
          <ShieldCheck size={16} />
          Explicit by design
        </span>
        <div className="visual-card">
          <span className="visual-icon">
            <Shield size={38} />
          </span>
          <p className="eyebrow">A clear chain of trust</p>
          <h2>
            People → projects
            <br />→ resources.
          </h2>
          <p>
            Organization boundaries stay visible.
            <br />
            Permissions stay intentional.
          </p>
          <div className="visual-chain">
            <span>Membership</span>
            <i />
            <span>Entitlement</span>
            <i />
            <span>Grant</span>
          </div>
        </div>
        <span className="visual-caption">One workspace. Precisely scoped.</span>
      </aside>
    </main>
  );
}

export function App() {
  const session = useQuery({
    queryKey: ['session'],
    queryFn: async ({ signal }) => {
      const value = await read<Session>('/api/v1/me', signal);
      setCsrfToken(value.csrf_token);
      return value;
    },
    retry: false,
  });
  useEffect(() => {
    setCsrfToken(session.data?.csrf_token ?? '');
  }, [session.data?.csrf_token]);
  if (window.location.pathname.startsWith('/invitations/accept'))
    return <InvitationAcceptance session={session.data} loading={session.isPending} />;
  if (session.isPending)
    return (
      <div className="initial-loading">
        <Brand />
        <Loading label="Opening your workspace" />
      </div>
    );
  if (!session.data)
    return (
      <SignIn
        unavailable={
          session.error instanceof ApiError && session.error.status === 401
            ? undefined
            : session.error
        }
      />
    );
  return <Workspace session={session.data} />;
}

function Workspace({ session }: { session: Session }) {
  const [route, setRoute] = useState(routeFromLocation);
  const [mobileOpen, setMobileOpen] = useState(false);
  const client = useQueryClient();
  const organizations = useQuery({
    queryKey: ['organizations', session.id],
    queryFn: ({ signal }) =>
      read<Schema<'OrganizationPage'>>('/api/v1/organizations?limit=100', signal),
  });
  const organization = route.organization || organizations.data?.items[0]?.id || '';
  const projects = useQuery({
    queryKey: ['scope', session.id, organization, 'projects'],
    queryFn: ({ signal }) =>
      read<Schema<'ProjectPage'>>(scopedPath(organization, '/projects?limit=100'), signal),
    enabled: Boolean(organization),
  });
  const project = route.project || projects.data?.items[0]?.id || '';
  const membership = session.memberships.find((item) => item.organization_id === organization);
  const isManager = membership?.role === 'access_manager' && membership.status === 'active';
  const isReviewer = Boolean(isManager && membership?.can_review_migration);
  const organizationData = organizations.data?.items.find((item) => item.id === organization);
  const projectData = projects.data?.items.find((item) => item.id === project);
  const scope: Scope = { user: session.id, organization, project };
  useEffect(() => {
    const update = () => {
      setRoute(routeFromLocation());
      setMobileOpen(false);
    };
    window.addEventListener('popstate', update);
    return () => window.removeEventListener('popstate', update);
  }, []);
  useEffect(() => {
    if (organization && project && (!route.organization || !route.project)) {
      window.history.replaceState(
        {},
        '',
        `/workspace?${new URLSearchParams({ organization, project, view: route.view })}`,
      );
    }
  }, [organization, project, route.organization, route.project, route.view]);
  const switchScope = async (nextOrganization: string, nextProject: string, view = route.view) => {
    if (
      document.body.dataset.scopeDraft === 'true' &&
      !window.confirm('Discard the current draft and change scope?')
    )
      return;
    await client.cancelQueries({
      predicate: (query) => query.queryKey[0] === 'scope' && query.queryKey[2] === organization,
    });
    client.removeQueries({
      predicate: (query) => query.queryKey[0] === 'scope' && query.queryKey[2] === organization,
    });
    navigateWorkspace(nextOrganization, nextProject, view);
  };
  const logout = useMutation({
    mutationFn: () => request('/api/v1/logout', { method: 'POST' }),
    onSuccess: () => {
      client.clear();
      setCsrfToken('');
      window.location.assign('/');
    },
  });
  const allowedNavigation = navigation.filter(
    (item) =>
      !('manager' in item && item.manager && !isManager) &&
      !('reviewer' in item && item.reviewer && !isReviewer),
  );
  const viewAllowed = allowedNavigation.some((item) => item.view === route.view);

  return (
    <div className="app-shell">
      {mobileOpen && (
        <button
          className="sidebar-overlay"
          aria-label="Close navigation"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside id="workspace-navigation" className={`sidebar ${mobileOpen ? 'sidebar-open' : ''}`}>
        <div className="sidebar-brand">
          <Brand />
          <button
            className="icon-button mobile-close"
            aria-label="Close navigation"
            onClick={() => setMobileOpen(false)}
          >
            <X size={20} />
          </button>
        </div>
        <div className="workspace-label">
          <span className="workspace-symbol">{initials(organizationData?.name)}</span>
          <div>
            <strong>{organizationData?.name ?? 'Your workspace'}</strong>
            <small>Organization workspace</small>
          </div>
        </div>
        <p className="nav-label">Workspace</p>
        <nav aria-label="Main navigation">
          {allowedNavigation.map(({ view, title, icon: Icon }) => (
            <button
              key={view}
              aria-current={route.view === view ? 'page' : undefined}
              className={`nav-item ${route.view === view ? 'nav-active' : ''}`}
              onClick={() => {
                navigateWorkspace(organization, project, view as View);
                setMobileOpen(false);
              }}
            >
              <Icon size={18} />
              <span>{title}</span>
              {route.view === view && <span className="nav-active-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="scope-note">
            <ShieldCheck size={19} />
            <strong>Intentional access</strong>
            <p>
              Membership opens the door.
              <br />
              Grants define what’s inside.
            </p>
          </div>
          <div className="sidebar-help">
            <CircleHelp size={17} />
            <span>Changes are always recorded</span>
          </div>
          <div className="user-card">
            <span className="avatar">{initials(session.display_name)}</span>
            <div>
              <strong>{session.display_name ?? session.email}</strong>
              <small>
                {membership?.kind === 'staff'
                  ? 'Operations reviewer'
                  : isManager
                    ? 'Access manager'
                    : 'Workspace member'}
              </small>
            </div>
            <button
              className="icon-button"
              aria-label="Sign out"
              onClick={() => logout.mutate()}
              disabled={logout.isPending}
            >
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </aside>
      <div className="workspace-main" inert={mobileOpen || undefined}>
        <header className="topbar">
          <div className="scope-controls">
            <button
              className="icon-button mobile-menu"
              aria-label="Open navigation"
              aria-controls="workspace-navigation"
              aria-expanded={mobileOpen}
              onClick={() => setMobileOpen(true)}
            >
              <Menu size={22} />
            </button>
            <div className="scope-select">
              <label htmlFor="organization">Organization</label>
              <div>
                <select
                  id="organization"
                  value={organization}
                  onChange={(event) => void switchScope(event.target.value, '', 'overview')}
                  aria-label="Organization"
                >
                  {organizations.data?.items.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
                <ChevronDown size={15} />
              </div>
            </div>
            <span className="scope-divider">/</span>
            <div className="scope-select">
              <label htmlFor="project">Project</label>
              <div>
                <FolderClosed size={15} />
                <select
                  id="project"
                  value={project}
                  onChange={(event) => void switchScope(organization, event.target.value)}
                  aria-label="Project"
                >
                  {projects.data?.items.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
                <ChevronDown size={15} />
              </div>
            </div>
          </div>
          <div className="topbar-status">
            <Badge tone="green">Scoped workspace</Badge>
            <span className="topbar-icon">
              <Command size={16} />
            </span>
          </div>
        </header>
        <main id="main-content" key={`${organization}:${project}`}>
          {organizations.error ? (
            <ErrorPanel error={organizations.error} retry={() => void organizations.refetch()} />
          ) : projects.error ? (
            <ErrorPanel error={projects.error} retry={() => void projects.refetch()} />
          ) : organizations.isPending || (Boolean(organization) && projects.isPending) ? (
            <Loading />
          ) : !organizationData ? (
            <Empty
              title="This organization is unavailable"
              detail="Choose an organization assigned to your identity. Access is never inferred from a shared link."
            />
          ) : !projectData ? (
            <Empty
              title="No project selected"
              detail="This organization has no available projects. An access manager can create one."
            />
          ) : !viewAllowed ? (
            <Empty
              title="This workspace view is unavailable"
              detail="Your current membership does not have permission to open this view."
            />
          ) : (
            <WorkspaceView
              view={route.view}
              scope={scope}
              session={session}
              organization={organizationData}
              project={projectData}
              isManager={isManager}
            />
          )}
        </main>
        <footer className="workspace-footer">
          <span>
            Scopegate<span className="brand-dot">.</span> Access, with clarity.
          </span>
          <span>
            <span className="footer-dot" />
            Organization boundaries enforced
          </span>
        </footer>
      </div>
    </div>
  );
}

function WorkspaceView({
  view,
  scope,
  session,
  organization,
  project,
  isManager,
}: {
  view: View;
  scope: Scope;
  session: Session;
  organization: Schema<'Organization'>;
  project: Schema<'Project'>;
  isManager: boolean;
}) {
  const props = { scope, session, organization, project, isManager };
  switch (view) {
    case 'resources':
      return <Resources {...props} />;
    case 'members':
      return <Members {...props} />;
    case 'invitations':
      return <Invitations {...props} />;
    case 'activity':
      return <Activity scope={scope} />;
    case 'migration':
      return <Migration scope={scope} session={session} />;
    default:
      return <Overview {...props} />;
  }
}
