import * as React from 'react';
import type { AuditAction, AuditEntry, AuditFilters } from '../../api/auth2';
import { api, errorMessage } from '../../api/client';
import type { Paginated } from '../../api/types';
import { Empty, Loader, Pagination } from '../../components/Common';
import { formatDateTime } from '../../utils/format';

const ACTIONS: { value: AuditAction; label: string; badge: string }[] = [
  { value: 'create', label: 'Create', badge: 'bg-success' },
  { value: 'update', label: 'Update', badge: 'bg-primary' },
  { value: 'delete', label: 'Delete', badge: 'bg-danger' },
  { value: 'login', label: 'Login', badge: 'bg-info text-dark' },
  { value: 'login_failed', label: 'Login failed', badge: 'bg-warning text-dark' },
  { value: 'other', label: 'Other', badge: 'bg-secondary' },
];

const actionInfo = (a: AuditAction) => ACTIONS.find((x) => x.value === a) ?? ACTIONS[ACTIONS.length - 1];

const PAGE_SIZE = 25;

interface AuditLogState {
  data: Paginated<AuditEntry> | null;
  filters: Required<Omit<AuditFilters, 'page'>>;
  page: number;
  error: string;
  open: Set<number>;
}

/** Administrators: who changed what in the panel, plus sign-in attempts. */
class AuditLog extends React.Component<Record<string, never>, AuditLogState> {
  public state: AuditLogState = {
    data: null,
    filters: { user: '', action: '', from: '', to: '', search: '' },
    page: 1,
    error: '',
    open: new Set(),
  };

  private mounted = false;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private seq = 0;

  public componentDidMount(): void {
    this.mounted = true;
    this.scheduleLoad(0);
  }

  public componentDidUpdate(_p: Record<string, never>, prev: AuditLogState): void {
    if (prev.filters !== this.state.filters || prev.page !== this.state.page) this.scheduleLoad(250);
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.timer);
  }

  private scheduleLoad(delay: number): void {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.load(), delay);
  }

  private load(): void {
    const { filters, page } = this.state;
    const params: Record<string, string | number> = { page, page_size: PAGE_SIZE };
    (Object.keys(filters) as (keyof typeof filters)[]).forEach((k) => {
      if (filters[k].trim()) params[k] = filters[k].trim();
    });
    const seq = ++this.seq;
    api
      .get<Paginated<AuditEntry>>('/admin/audit/', { params })
      .then((r) => this.mounted && seq === this.seq && this.setState({ data: r.data, error: '' }))
      .catch((err) => this.mounted && seq === this.seq && this.setState({ data: { count: 0, next: null, previous: null, results: [] }, error: errorMessage(err) }));
  }

  private setFilter = (k: keyof AuditLogState['filters']) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>): void =>
    this.setState({ filters: { ...this.state.filters, [k]: e.target.value }, page: 1 });

  private clear = (): void => {
    this.setState({ filters: { user: '', action: '', from: '', to: '', search: '' }, page: 1 });
  };

  private toggle(id: number): void {
    this.setState((s) => {
      const open = new Set(s.open);
      if (open.has(id)) open.delete(id);
      else open.add(id);
      return { open };
    });
  }

  private static hasChanges(changes: unknown): boolean {
    if (!changes) return false;
    if (Array.isArray(changes)) return changes.length > 0;
    if (typeof changes === 'object') return Object.keys(changes as object).length > 0;
    return true;
  }

  public render(): React.ReactNode {
    const { data, filters, page, error, open } = this.state;
    const filtered = Object.values(filters).some((v) => v.trim());
    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2">
          <h1 className="h2 mb-0"><i className="bi bi-journal-text me-2 text-accent" aria-hidden="true" />Audit log</h1>
          {data && <span className="text-muted">{data.count} entries</span>}
        </div>
        <p className="text-muted small mb-4">
          Changes made by staff and administrators through the panel, and every sign-in attempt. Passwords, codes and tokens are never stored.
        </p>

        <div className="card border-0 shadow-sm mb-3">
          <div className="card-body">
            <div className="row g-2 align-items-end">
              <div className="col-md-4">
                <label htmlFor="al-search" className="form-label small text-muted mb-1">Search</label>
                <input id="al-search" className="form-control" placeholder="Path, object, email or IP…" value={filters.search} onChange={this.setFilter('search')} />
              </div>
              <div className="col-md-2">
                <label htmlFor="al-user" className="form-label small text-muted mb-1">User</label>
                <input id="al-user" className="form-control" placeholder="Email or id" value={filters.user} onChange={this.setFilter('user')} />
              </div>
              <div className="col-md-2">
                <label htmlFor="al-action" className="form-label small text-muted mb-1">Action</label>
                <select id="al-action" className="form-select" value={filters.action} onChange={this.setFilter('action')}>
                  <option value="">All actions</option>
                  {ACTIONS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
                </select>
              </div>
              <div className="col-6 col-md-2">
                <label htmlFor="al-from" className="form-label small text-muted mb-1">From</label>
                <input id="al-from" type="date" className="form-control" value={filters.from} onChange={this.setFilter('from')} />
              </div>
              <div className="col-6 col-md-2">
                <label htmlFor="al-to" className="form-label small text-muted mb-1">To</label>
                <input id="al-to" type="date" className="form-control" value={filters.to} onChange={this.setFilter('to')} />
              </div>
            </div>
            {filtered && (
              <button type="button" className="btn btn-link btn-sm px-0 mt-2" onClick={this.clear}>
                <i className="bi bi-x-circle me-1" aria-hidden="true" />Clear filters
              </button>
            )}
          </div>
        </div>
        {error && <div className="alert alert-danger">{error}</div>}

        {data === null ? (
          <Loader />
        ) : data.count === 0 ? (
          <Empty title="No audit entries" />
        ) : (
          <>
            <div className="card border-0 shadow-sm">
              <div className="table-responsive">
                <table className="table table-hover align-middle mb-0 small">
                  <thead className="table-light">
                    <tr><th style={{ width: 32 }} /><th>When</th><th>User</th><th>Action</th><th>Request</th><th>Object</th><th className="text-end">Status</th><th>IP</th></tr>
                  </thead>
                  <tbody>
                    {data.results.map((e) => {
                      const info = actionInfo(e.action);
                      const expandable = AuditLog.hasChanges(e.changes);
                      const isOpen = open.has(e.id);
                      return (
                        <React.Fragment key={e.id}>
                          <tr>
                            <td>
                              {expandable && (
                                <button
                                  type="button"
                                  className="btn btn-sm btn-link p-0"
                                  aria-expanded={isOpen}
                                  aria-label={isOpen ? 'Hide details' : 'Show details'}
                                  onClick={() => this.toggle(e.id)}
                                >
                                  <i className={`bi bi-chevron-${isOpen ? 'down' : 'right'}`} aria-hidden="true" />
                                </button>
                              )}
                            </td>
                            <td className="text-nowrap">{formatDateTime(e.at)}</td>
                            <td>
                              {e.user_email ? (
                                <>
                                  <div>{e.user_email}</div>
                                  {e.user_name && <div className="text-muted">{e.user_name}</div>}
                                </>
                              ) : (
                                <span className="text-muted">—</span>
                              )}
                            </td>
                            <td><span className={`badge ${info.badge}`}>{info.label}</span></td>
                            <td className="text-break"><code className="text-dark">{e.method}</code> {e.path}</td>
                            <td className="text-break">{e.object_repr || '—'}</td>
                            <td className={`text-end ${e.status_code && e.status_code >= 400 ? 'text-danger' : ''}`}>{e.status_code ?? '—'}</td>
                            <td className="text-muted text-nowrap">{e.ip ?? '—'}</td>
                          </tr>
                          {isOpen && (
                            <tr>
                              <td />
                              <td colSpan={7} className="bg-light">
                                <pre className="mb-0 small" style={{ whiteSpace: 'pre-wrap', maxHeight: 360, overflow: 'auto' }}>
                                  {JSON.stringify(e.changes, null, 2)}
                                </pre>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="mt-3">
              <Pagination page={page} count={data.count} pageSize={PAGE_SIZE} onChange={(p: number) => this.setState({ page: p })} />
            </div>
          </>
        )}
      </div>
    );
  }
}

export default AuditLog;
