import { useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRight,
  BookOpen,
  Check,
  ChevronDown,
  Globe2,
  LayoutGrid,
  List,
  LockKeyhole,
  SearchX,
  ShieldCheck,
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
import { CommandKeys, read, scopedPath, write, type Schema } from '../lib/api';
import { usePagedQuery } from '../lib/queries';
import { scopeKey, type Scope } from '../lib/workspace';

export function Resources({
  scope,
  project,
  isManager,
}: {
  scope: Scope;
  project: Schema<'Project'>;
  isManager: boolean;
}) {
  const [search, setSearch] = useState('');
  const [locale, setLocale] = useState('en');
  const [view, setView] = useState<'granted' | 'entitled'>('granted');
  const [display, setDisplay] = useState<'grid' | 'list'>('grid');
  return (
    <>
      <PageHeading
        eyebrow={`Workspace / ${project.name}`}
        title="Resource library"
        description="Discover the resources available in your project. Open one to verify your current access."
        action={
          <span className="heading-icon">
            <BookOpen size={22} />
          </span>
        }
      />
      <div className="library-tabs">
        <button
          className={view === 'granted' ? 'tab-active' : ''}
          onClick={() => setView('granted')}
        >
          My resources<span>Explicit grants</span>
        </button>
        {isManager && (
          <button
            className={view === 'entitled' ? 'tab-active' : ''}
            onClick={() => setView('entitled')}
          >
            Project collection<span>Management view</span>
          </button>
        )}
      </div>
      <div className="toolbar">
        <SearchBox
          value={search}
          onChange={setSearch}
          placeholder="Search titles, tags, or resource keys…"
        />
        <div className="toolbar-actions">
          <label className="filter-select">
            <Globe2 size={15} />
            <span className="sr-only">Resource language</span>
            <select
              value={locale}
              onChange={(event) => setLocale(event.target.value)}
              aria-label="Resource language"
            >
              <option value="en">English</option>
              <option value="pt">Português</option>
              <option value="es">Español</option>
              <option value="fr">Français</option>
            </select>
            <ChevronDown size={13} />
          </label>
          <div className="display-switch">
            <button
              aria-label="Grid view"
              aria-pressed={display === 'grid'}
              onClick={() => setDisplay('grid')}
            >
              <LayoutGrid size={17} />
            </button>
            <button
              aria-label="List view"
              aria-pressed={display === 'list'}
              onClick={() => setDisplay('list')}
            >
              <List size={17} />
            </button>
          </div>
        </div>
      </div>
      {view === 'entitled' && (
        <Notice tone="amber">
          This management view shows the project collection. It does not grant you permission to
          open these resources.
        </Notice>
      )}
      <ResourcePage
        key={`${search}:${locale}:${view}`}
        scope={scope}
        search={search}
        locale={locale}
        view={view}
        display={display}
      />
    </>
  );
}

function ResourcePage({
  scope,
  search,
  locale,
  view,
  display,
}: {
  scope: Scope;
  search: string;
  locale: string;
  view: string;
  display: string;
}) {
  const resources = usePagedQuery<Schema<'Resource'>>(
    scopeKey(scope, 'resource-page'),
    scopedPath(scope.organization, `/projects/${scope.project}/resources`),
    { q: search, locale, view },
  );
  const [selected, setSelected] = useState<Schema<'Resource'> | null>(null);
  if (resources.isPending) return <Loading label="Loading scoped resources" />;
  if (resources.error)
    return <ErrorPanel error={resources.error} retry={() => void resources.refetch()} />;
  if (!resources.data?.items.length)
    return (
      <Empty
        title={search ? 'No resources match this search' : 'No resources granted yet'}
        detail={
          search
            ? 'Try a different title or tag. Search stays within this project.'
            : 'Your membership is active. An access manager must assign individual resources before you can open them.'
        }
        action={search ? <SearchX size={24} /> : undefined}
      />
    );
  return (
    <>
      <div className="results-label">
        <span>{resources.data.items.length} resources on this page</span>
        <span>
          <ShieldCheck size={13} />
          {view === 'granted' ? 'Your explicit grants' : 'Entitled to this project'}
        </span>
      </div>
      <div className={`resource-grid ${display === 'list' ? 'resource-list' : ''}`}>
        {resources.data.items.map((resource, index) => (
          <article className="resource-card" key={resource.id}>
            <div className={`resource-card-art resource-art-${index % 4}`}>
              <ResourcePattern index={index} />
              <span className="resource-category">{resource.tags?.[0] ?? 'Resource'}</span>
              <span className="resource-lock">
                <LockKeyhole size={14} />
              </span>
            </div>
            <div className="resource-card-body">
              <div className="resource-meta">
                <code>{resource.external_key}</code>
                <Badge tone={resource.status === 'published' ? 'green' : 'neutral'}>
                  {resource.status}
                </Badge>
              </div>
              <h2>{resource.title ?? `Resource ${resource.external_key}`}</h2>
              <p>
                {resource.description ??
                  'Published resource available within this project’s access boundary.'}
              </p>
              {resource.fallback_used && (
                <span className="fallback-label">
                  <Globe2 size={12} />
                  Showing {resource.locale?.toUpperCase() ?? 'default'} fallback
                </span>
              )}
              <div className="resource-card-footer">
                <span>
                  <BookOpen size={14} />
                  {resource.tags?.[1] ?? 'Workspace resource'}
                </span>
                <button className="text-link" onClick={() => setSelected(resource)}>
                  Open resource
                  <ArrowRight size={15} />
                </button>
              </div>
            </div>
          </article>
        ))}
      </div>
      <Pagination
        page={resources.page}
        hasNext={Boolean(resources.data.next_cursor)}
        next={resources.next}
        previous={resources.previous}
      />
      {selected && (
        <ResourceAdmission scope={scope} resource={selected} onClose={() => setSelected(null)} />
      )}
    </>
  );
}

function ResourceAdmission({
  scope,
  resource,
  onClose,
}: {
  scope: Scope;
  resource: Schema<'Resource'>;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const keys = useRef(new CommandKeys());
  const admission = useMutation({
    mutationFn: async () => {
      const path = scopedPath(scope.organization, `/projects/${scope.project}/report-configs`);
      const payload = {
        name: `Resource session · ${(resource.title ?? resource.external_key).slice(0, 150)}`,
        resource_ids: [resource.id],
      };
      const report = await write<Schema<'ReportConfig'>>(
        path,
        payload,
        keys.current.get(path, payload),
      );
      return read<Schema<'ReportConfig'>>(`${path}/${report.id}`);
    },
    onError: () => {
      void client.invalidateQueries({ queryKey: scopeKey(scope, 'resource-page') });
    },
  });
  return (
    <Dialog
      title={resource.title ?? resource.external_key}
      subtitle="Protected resource session"
      onClose={onClose}
    >
      <div className="dialog-body">
        <div className="resource-detail-icon">
          <BookOpen size={30} />
        </div>
        <p className="resource-detail-description">
          {resource.description ?? 'Open a protected reference to this published resource.'}
        </p>
        <div className="detail-facts">
          <div>
            <span>Stable resource key</span>
            <strong>{resource.external_key}</strong>
          </div>
          <div>
            <span>Catalog revision</span>
            <strong>v{resource.catalog_version}</strong>
          </div>
          <div>
            <span>Current access</span>
            <strong>
              {admission.isSuccess ? 'Verified by the server' : 'Verified when you open'}
            </strong>
          </div>
        </div>
        {admission.error && <ErrorPanel error={admission.error} />}
        {admission.isSuccess && (
          <Notice>
            <span>
              <strong>Access confirmed.</strong> A protected reference was created and rechecked.
              Reference {admission.data.id.slice(0, 8)}.
            </span>
          </Notice>
        )}
        <p className="form-help">
          Opening creates a protected report reference. Membership, entitlement, publication, and
          your individual grant are checked again.
        </p>
      </div>
      <div className="dialog-footer">
        <Button className="button-ghost" onClick={onClose}>
          Close
        </Button>
        <Button
          className="button-dark"
          pending={admission.isPending}
          disabled={admission.isSuccess}
          onClick={() => admission.mutate()}
        >
          {admission.isSuccess ? <Check size={16} /> : <ShieldCheck size={16} />}
          {admission.isSuccess ? 'Access verified' : 'Open protected resource'}
        </Button>
      </div>
    </Dialog>
  );
}

function ResourcePattern({ index }: { index: number }) {
  return (
    <svg className="resource-pattern" viewBox="0 0 320 170" aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth="1.25">
        {index % 4 === 0 ? (
          <>
            {[0, 1, 2, 3].map((i) => (
              <ellipse
                key={i}
                cx="160"
                cy="85"
                rx={36 + i * 15}
                ry={36 + i * 7}
                transform={`rotate(${i * 24} 160 85)`}
              />
            ))}
            <circle cx="160" cy="85" r="8" fill="currentColor" />
          </>
        ) : index % 4 === 1 ? (
          <>
            {[0, 1, 2, 3, 4].map((i) => (
              <path key={i} d={`M${75 + i * 17} 123 ${118 + i * 14} 44 ${161 + i * 17} 123Z`} />
            ))}
          </>
        ) : index % 4 === 2 ? (
          <>
            {[0, 1, 2, 3, 4].map((i) => (
              <rect
                key={i}
                x={108 + i * 9}
                y={34 + i * 7}
                width="70"
                height="70"
                rx="8"
                transform="rotate(-18 160 85)"
              />
            ))}
          </>
        ) : (
          <>
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <circle key={i} cx={105 + i * 20} cy="85" r="33" />
            ))}
          </>
        )}
      </g>
    </svg>
  );
}
