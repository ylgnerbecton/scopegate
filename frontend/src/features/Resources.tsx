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
  ShieldCheck,
} from 'lucide-react';
import {
  Badge,
  Button,
  ChoiceGroup,
  Dialog,
  Empty,
  ErrorPanel,
  Loading,
  Notice,
  PageHeading,
  SearchBox,
} from '../components/ui';
import { Pagination } from '../components/Pagination';
import { ResourceVisual } from '../components/ResourceVisual';
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
      <ChoiceGroup<'granted' | 'entitled'>
        label="Resource scope"
        value={view}
        onChange={setView}
        options={[
          { value: 'granted', label: 'My resources', detail: 'Explicit grants' },
          ...(isManager
            ? [
                {
                  value: 'entitled' as const,
                  label: 'Project collection',
                  detail: 'Management view',
                },
              ]
            : []),
        ]}
      />
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
          <ChoiceGroup<'grid' | 'list'>
            label="Resource layout"
            variant="compact"
            value={display}
            onChange={setDisplay}
            options={[
              { value: 'grid', label: 'Grid view', icon: <LayoutGrid size={17} /> },
              { value: 'list', label: 'List view', icon: <List size={17} /> },
            ]}
          />
        </div>
      </div>
      {view === 'entitled' && (
        <Notice tone="amber">
          This management view shows the project collection. It does not grant you permission to
          open these resources.
        </Notice>
      )}
      <ResourcePage
        scope={scope}
        search={search}
        locale={locale}
        view={view}
        display={display}
        resetSearch={() => setSearch('')}
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
  resetSearch,
}: {
  scope: Scope;
  search: string;
  locale: string;
  view: string;
  display: string;
  resetSearch: () => void;
}) {
  const resources = usePagedQuery<Schema<'Resource'>>(
    scopeKey(scope, 'resource-page'),
    scopedPath(scope.organization, `/projects/${scope.project}/resources`),
    { q: search, locale, view },
  );
  const [selected, setSelected] = useState<Schema<'Resource'> | null>(null);
  return (
    <>
      {resources.isPending ? (
        <Loading label="Loading scoped resources" />
      ) : resources.error ? (
        <ErrorPanel error={resources.error} retry={() => void resources.refetch()} />
      ) : !resources.data?.items.length ? (
        <Empty
          title={
            search
              ? 'No resources match this search'
              : resources.page > 1
                ? 'This page has no resources'
                : view === 'entitled'
                  ? 'No resources entitled to this project'
                  : 'No resources granted yet'
          }
          detail={
            search
              ? 'Try a different title or tag. Search stays within this project.'
              : resources.page > 1
                ? 'The collection may have changed. Return to the previous page to continue.'
                : view === 'entitled'
                  ? 'An entitled, published resource must be added before it can be granted. Management authority does not bypass this boundary.'
                  : 'Your membership is active. An access manager must assign individual resources before you can open them.'
          }
          action={
            search ? (
              <Button className="button-ghost" onClick={resetSearch}>
                Reset search
              </Button>
            ) : undefined
          }
        />
      ) : (
        <>
          <div className="results-label">
            <span role="status">
              {resources.data.items.length}{' '}
              {resources.data.items.length === 1 ? 'resource' : 'resources'} on this page
              {resources.isFetching ? ' · Refreshing' : ''}
            </span>
            <span>
              <ShieldCheck size={13} />
              {view === 'granted' ? 'Your explicit grants' : 'Entitled to this project'}
            </span>
          </div>
          <div className={`resource-grid ${display === 'list' ? 'resource-list' : ''}`}>
            {resources.data.items.map((resource) => (
              <article className="resource-card" key={resource.id}>
                <ResourceVisual className="resource-card-art" resourceKey={resource.external_key}>
                  <span className="resource-category">{resource.tags?.[0] ?? 'Resource'}</span>
                  <span className="resource-lock">
                    <LockKeyhole size={14} />
                  </span>
                </ResourceVisual>
                <div className="resource-card-body">
                  <div className="resource-meta">
                    <code>{resource.external_key}</code>
                    <Badge tone={resource.status === 'published' ? 'green' : 'neutral'}>
                      {resource.status}
                    </Badge>
                  </div>
                  <h2>{resource.title ?? `Resource ${resource.external_key}`}</h2>
                  {resource.description && <p>{resource.description}</p>}
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
        </>
      )}
      <Pagination
        page={resources.page}
        hasNext={resources.hasNext}
        next={resources.next}
        previous={resources.previous}
        busy={resources.isFetching}
        label="Resource pages"
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
        {resource.description && (
          <p className="resource-detail-description">{resource.description}</p>
        )}
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
