export type View = 'overview' | 'resources' | 'members' | 'invitations' | 'activity' | 'migration';
export type Scope = { user: string; organization: string; project: string };
const views: View[] = ['overview', 'resources', 'members', 'invitations', 'activity', 'migration'];

export function routeFromLocation() {
  const query = new URLSearchParams(window.location.search);
  const value = query.get('view');
  return {
    organization: query.get('organization') ?? '',
    project: query.get('project') ?? '',
    view: views.includes(value as View) ? (value as View) : 'overview',
  };
}
export function navigateWorkspace(organization: string, project: string, view: View) {
  const query = new URLSearchParams({ organization, project, view });
  window.history.pushState({}, '', `/workspace?${query}`);
  window.dispatchEvent(new PopStateEvent('popstate'));
}
export function scopeKey(scope: Scope, resource: string, ...detail: unknown[]) {
  return ['scope', scope.user, scope.organization, scope.project, resource, ...detail] as const;
}
export function initials(name?: string | null) {
  return (name ?? 'Member')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join('')
    .toUpperCase();
}
export function displayDate(value: string) {
  return new Intl.DateTimeFormat('en', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}
export function humanize(value: string) {
  return value.replaceAll(/[._]/g, ' ').replace(/^./, (letter) => letter.toUpperCase());
}
