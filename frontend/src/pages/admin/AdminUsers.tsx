import * as React from 'react';
import { api, errorMessage } from '../../api/client';
import type { AssignedMuseum, StaffMuseums } from '../../api/reports';
import type { MuseumSummary, Paginated, Role, User } from '../../api/types';
import { Empty, Loader, Pagination } from '../../components/Common';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { formatDate, formatDateTime } from '../../utils/format';
import { placeLocation } from '../../utils/format';

const ROLES: { value: Role; label: string }[] = [
  { value: 'visitor', label: 'Visitor' },
  { value: 'staff', label: 'Museum staff' },
  { value: 'admin', label: 'Administrator' },
  { value: 'partner', label: 'Partner (read-only portal)' },
];

/** Roles whose places are edited in the inline panel: staff work there, partners only see the figures. */
type PlacesKind = 'staff' | 'partner';

const placesUrl = (kind: PlacesKind, userId: number): string =>
  kind === 'partner' ? `/auth/users/${userId}/partner-places/` : `/admin/staff/${userId}/museums/`;

interface StaffMuseumsPanelProps {
  user: User;
  /** Staff assignments (Museum.staff) or a partner's portal places (User.partner_places). */
  kind: PlacesKind;
  onClose: () => void;
}

interface StaffMuseumsPanelState {
  assigned: AssignedMuseum[] | null;
  search: string;
  options: MuseumSummary[];
  saving: boolean;
  dirty: boolean;
  error: string;
  notice: string;
}

/** Inline editor for the places a staff member works at (desk, gate, reports are limited to these). */
class StaffMuseumsPanel extends React.Component<StaffMuseumsPanelProps, StaffMuseumsPanelState> {
  public state: StaffMuseumsPanelState = { assigned: null, search: '', options: [], saving: false, dirty: false, error: '', notice: '' };

  private mounted = false;
  private timer: ReturnType<typeof setTimeout> | undefined;

  public componentDidMount(): void {
    this.mounted = true;
    api
      .get<StaffMuseums>(placesUrl(this.props.kind, this.props.user.id))
      .then((r) => this.mounted && this.setState({ assigned: r.data.museums }))
      .catch((err) => this.mounted && this.setState({ assigned: [], error: errorMessage(err) }));
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.timer);
  }

  private onSearch = (search: string): void => {
    this.setState({ search });
    clearTimeout(this.timer);
    if (!search.trim()) {
      this.setState({ options: [] });
      return;
    }
    this.timer = setTimeout(() => {
      api
        .get<Paginated<MuseumSummary>>('/museums/', { params: { search } })
        .then((r) => this.mounted && this.setState({ options: r.data.results }))
        .catch(() => undefined);
    }, 250);
  };

  private add = (m: MuseumSummary): void => {
    this.setState((s) => ({
      assigned: (s.assigned ?? []).some((a) => a.slug === m.slug)
        ? s.assigned
        : [...(s.assigned ?? []), { slug: m.slug, name: m.name, city_name: m.city_name, state_name: m.state_name }],
      search: '',
      options: [],
      dirty: true,
      notice: '',
    }));
  };

  private remove = (slug: string): void => {
    this.setState((s) => ({ assigned: (s.assigned ?? []).filter((a) => a.slug !== slug), dirty: true, notice: '' }));
  };

  private save = async (): Promise<void> => {
    this.setState({ saving: true, error: '', notice: '' });
    try {
      const { data } = await api.put<StaffMuseums>(placesUrl(this.props.kind, this.props.user.id), {
        museums: (this.state.assigned ?? []).map((a) => a.slug),
      });
      if (this.mounted) this.setState({ assigned: data.museums, dirty: false, notice: 'Saved.' });
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ saving: false });
    }
  };

  public render(): React.ReactNode {
    const { user, kind, onClose } = this.props;
    const { assigned, search, options, saving, dirty, error, notice } = this.state;
    const chosen = new Set((assigned ?? []).map((a) => a.slug));
    const inputId = `staff-museum-search-${user.id}`;
    return (
      <div className="card border-0 shadow-sm my-2">
        <div className="card-body">
          <div className="d-flex justify-content-between align-items-start gap-2 mb-2">
            <div>
              <h2 className="h6 mb-1"><i className="bi bi-building me-2 text-accent" aria-hidden="true" />Places for {user.email}</h2>
              <p className="text-muted small mb-0">
                {kind === 'partner'
                  ? 'This partner sees visitors, revenue, reviews and payouts of these places in the read-only partner portal. They cannot sell, scan or change anything.'
                  : 'This staff member can sell tickets, scan at the gate and see bookings and reports only for these places.'}
              </p>
            </div>
            <button type="button" className="btn-close" aria-label="Close" onClick={onClose} />
          </div>
          {error && <div className="alert alert-danger py-2 small">{error}</div>}
          {assigned === null ? (
            <Loader />
          ) : (
            <>
              <div className="d-flex flex-wrap gap-2 mb-3">
                {assigned.length === 0 && <span className="text-muted small">Not assigned to any place yet: this user will see {kind === 'partner' ? 'no figures' : 'no bookings'}.</span>}
                {assigned.map((a) => (
                  <span key={a.slug} className="badge rounded-pill bg-light text-dark border d-inline-flex align-items-center gap-1 py-2 px-3">
                    {a.name} <span className="text-muted fw-normal">· {a.city_name}</span>
                    <button type="button" className="btn-close ms-1" style={{ fontSize: '0.6rem' }} aria-label={`Remove ${a.name}`} onClick={() => this.remove(a.slug)} />
                  </span>
                ))}
              </div>
              <div className="row g-2 align-items-start">
                <div className="col-md-8 position-relative">
                  <label htmlFor={inputId} className="visually-hidden">Add a place</label>
                  <input
                    id={inputId}
                    className="form-control form-control-sm"
                    placeholder="Search a place to add…"
                    value={search}
                    autoComplete="off"
                    onChange={(e) => this.onSearch(e.target.value)}
                  />
                  {options.length > 0 && (
                    <div className="list-group shadow position-absolute" style={{ top: '100%', left: 4, right: 4, zIndex: 10, maxHeight: 260, overflowY: 'auto' }}>
                      {options.map((m) => (
                        <button type="button" key={m.id} className="list-group-item list-group-item-action small" disabled={chosen.has(m.slug)} onClick={() => this.add(m)}>
                          {m.name} <span className="text-muted">· {placeLocation(m.city_name, m.state_name)}</span>
                          {chosen.has(m.slug) && <i className="bi bi-check2 ms-2 text-success" aria-label="Already added" />}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <div className="col-md-4 d-flex gap-2 justify-content-md-end">
                  {notice && <span className="text-success small align-self-center"><i className="bi bi-check2-circle me-1" />{notice}</span>}
                  <button type="button" className="btn btn-sm btn-primary" disabled={saving || !dirty} onClick={this.save}>
                    {saving ? 'Saving…' : 'Save places'}
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    );
  }
}

interface NewPartnerFormProps {
  onCreated: (u: User) => void;
  onClose: () => void;
}

interface NewPartnerFormState {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  phone: string;
  places: AssignedMuseum[];
  search: string;
  options: MuseumSummary[];
  saving: boolean;
  error: string;
}

/** Admin -> Users -> Add partner: a sign-in for a place's management, linked to their places. */
class NewPartnerForm extends React.Component<NewPartnerFormProps, NewPartnerFormState> {
  public state: NewPartnerFormState = {
    email: '', password: '', first_name: '', last_name: '', phone: '', places: [], search: '', options: [], saving: false, error: '',
  };

  private mounted = false;
  private timer: ReturnType<typeof setTimeout> | undefined;

  public componentDidMount(): void {
    this.mounted = true;
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.timer);
  }

  private onSearch = (search: string): void => {
    this.setState({ search });
    clearTimeout(this.timer);
    if (!search.trim()) {
      this.setState({ options: [] });
      return;
    }
    this.timer = setTimeout(() => {
      api
        .get<Paginated<MuseumSummary>>('/museums/', { params: { search } })
        .then((r) => this.mounted && this.setState({ options: r.data.results }))
        .catch(() => undefined);
    }, 250);
  };

  private add = (m: MuseumSummary): void => {
    this.setState((s) => ({
      places: s.places.some((p) => p.slug === m.slug)
        ? s.places
        : [...s.places, { slug: m.slug, name: m.name, city_name: m.city_name, state_name: m.state_name }],
      search: '',
      options: [],
    }));
  };

  private removePlace = (slug: string): void => {
    this.setState((s) => ({ places: s.places.filter((x) => x.slug !== slug) }));
  };

  private submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { email, password, first_name, last_name, phone, places } = this.state;
    if (!places.length) {
      this.setState({ error: 'Choose at least one place.' });
      return;
    }
    this.setState({ saving: true, error: '' });
    try {
      const { data } = await api.post<User>('/auth/users/partners/', {
        email, password, first_name, last_name, phone, museums: places.map((p) => p.slug),
      });
      if (this.mounted) this.props.onCreated(data);
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ saving: false });
    }
  };

  public render(): React.ReactNode {
    const { email, password, first_name, last_name, phone, places, search, options, saving, error } = this.state;
    const chosen = new Set(places.map((p) => p.slug));
    return (
      <form className="card border-0 shadow-sm mb-3" onSubmit={this.submit}>
        <div className="card-body">
          <div className="d-flex justify-content-between align-items-start gap-2 mb-2">
            <div>
              <h2 className="h5 mb-1"><i className="bi bi-briefcase me-2 text-accent" aria-hidden="true" />Add a partner</h2>
              <p className="text-muted small mb-0">
                For a place&apos;s management: a read-only portal with visitors, revenue, reviews and payouts of their places. Not a panel user.
              </p>
            </div>
            <button type="button" className="btn-close" aria-label="Close" onClick={this.props.onClose} />
          </div>
          {error && <div className="alert alert-danger py-2 small">{error}</div>}
          <div className="row g-2">
            <div className="col-md-6">
              <label htmlFor="np-email" className="form-label small">Email</label>
              <input id="np-email" type="email" className="form-control" required autoComplete="off" value={email} onChange={(e) => this.setState({ email: e.target.value })} />
            </div>
            <div className="col-md-6">
              <label htmlFor="np-password" className="form-label small">Password</label>
              <input id="np-password" type="password" className="form-control" required minLength={8} autoComplete="new-password" value={password} onChange={(e) => this.setState({ password: e.target.value })} />
              <div className="form-text">Share it with the partner securely; they can change it from My profile.</div>
            </div>
            <div className="col-md-4">
              <label htmlFor="np-first" className="form-label small">First name</label>
              <input id="np-first" className="form-control" value={first_name} onChange={(e) => this.setState({ first_name: e.target.value })} />
            </div>
            <div className="col-md-4">
              <label htmlFor="np-last" className="form-label small">Last name</label>
              <input id="np-last" className="form-control" value={last_name} onChange={(e) => this.setState({ last_name: e.target.value })} />
            </div>
            <div className="col-md-4">
              <label htmlFor="np-phone" className="form-label small">Phone</label>
              <input id="np-phone" className="form-control" inputMode="tel" value={phone} onChange={(e) => this.setState({ phone: e.target.value })} />
            </div>
            <div className="col-12">
              <span className="form-label small d-block">Places</span>
              <div className="d-flex flex-wrap gap-2 mb-2">
                {places.length === 0 && <span className="text-muted small">No place chosen yet.</span>}
                {places.map((p) => (
                  <span key={p.slug} className="badge rounded-pill bg-light text-dark border d-inline-flex align-items-center gap-1 py-2 px-3">
                    {p.name} <span className="text-muted fw-normal">· {p.city_name}</span>
                    <button type="button" className="btn-close ms-1" style={{ fontSize: '0.6rem' }} aria-label={`Remove ${p.name}`} onClick={() => this.removePlace(p.slug)} />
                  </span>
                ))}
              </div>
              <div className="position-relative">
                <label htmlFor="np-place" className="visually-hidden">Add a place</label>
                <input id="np-place" className="form-control form-control-sm" placeholder="Search a place to add…" autoComplete="off" value={search} onChange={(e) => this.onSearch(e.target.value)} />
                {options.length > 0 && (
                  <div className="list-group shadow position-absolute" style={{ top: '100%', left: 4, right: 4, zIndex: 10, maxHeight: 260, overflowY: 'auto' }}>
                    {options.map((m) => (
                      <button type="button" key={m.id} className="list-group-item list-group-item-action small" disabled={chosen.has(m.slug)} onClick={() => this.add(m)}>
                        {m.name} <span className="text-muted">· {placeLocation(m.city_name, m.state_name)}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
          <div className="d-flex justify-content-end mt-3">
            <button className="btn btn-primary" disabled={saving}>{saving ? 'Creating…' : 'Create partner'}</button>
          </div>
        </div>
      </form>
    );
  }
}

interface AdminUsersProps extends WithAuthProps {}

interface AdminUsersState {
  data: Paginated<User> | null;
  page: number;
  search: string;
  role: string;
  error: string;
  /** Staff user whose place assignments are open in the inline panel. */
  museumsFor: number | null;
  exportOpen: boolean;
  /** Format being prepared, while the download is in progress. */
  exporting: ExportKind | null;
  /** "Add partner" form open. */
  addPartner: boolean;
  notice: string;
}

type ExportKind = 'xlsx' | 'csv' | 'pdf';

const EXPORTS: { kind: ExportKind; label: string; icon: string; hint: string }[] = [
  { kind: 'xlsx', label: 'Excel', icon: 'bi-file-earmark-spreadsheet', hint: 'Formatted sheet with filters' },
  { kind: 'csv', label: 'CSV', icon: 'bi-file-earmark-text', hint: 'Plain text, opens anywhere' },
  { kind: 'pdf', label: 'PDF', icon: 'bi-file-earmark-pdf', hint: 'Print-ready table' },
];

class AdminUsersPage extends React.Component<AdminUsersProps, AdminUsersState> {
  public state: AdminUsersState = {
    data: null,
    page: 1,
    search: '',
    role: '',
    error: '',
    museumsFor: null,
    exportOpen: false,
    exporting: null,
    addPartner: false,
    notice: '',
  };

  private exportMenu = React.createRef<HTMLDivElement>();

  private timer: ReturnType<typeof setTimeout> | undefined;
  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    this.scheduleLoad();
    document.addEventListener('mousedown', this.onOutside);
  }

  private onOutside = (e: MouseEvent): void => {
    if (this.state.exportOpen && !this.exportMenu.current?.contains(e.target as Node)) this.setState({ exportOpen: false });
  };

  /** Download the user list in the chosen format, with the same search/role filter as the table. */
  private download = async (kind: ExportKind): Promise<void> => {
    const { search, role } = this.state;
    this.setState({ exportOpen: false, exporting: kind, error: '' });
    try {
      const res = await api.get<Blob>('/auth/users/export/', {
        params: { kind, search: search || undefined, role: role || undefined },
        responseType: 'blob',
      });
      const disposition = String(res.headers['content-disposition'] ?? '');
      const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? `users.${kind}`;
      const url = URL.createObjectURL(res.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ exporting: null });
    }
  };

  public componentDidUpdate(_prevProps: AdminUsersProps, prevState: AdminUsersState): void {
    const s = this.state;
    if (s.page !== prevState.page || s.search !== prevState.search || s.role !== prevState.role) {
      this.scheduleLoad();
    }
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.timer);
    document.removeEventListener('mousedown', this.onOutside);
  }

  private scheduleLoad(): void {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      const { page, search, role } = this.state;
      api
        .get<Paginated<User>>('/auth/users/', { params: { page, search: search || undefined, role: role || undefined } })
        .then((r) => {
          if (this.mounted) this.setState({ data: r.data });
        });
    }, 250);
  }

  private update = async (u: User, patch: Partial<User>): Promise<void> => {
    try {
      const { data: updated } = await api.patch<User>(`/auth/users/${u.id}/`, patch);
      this.setState((s) => ({ data: s.data && { ...s.data, results: s.data.results.map((x) => (x.id === u.id ? updated : x)) } }));
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    }
  };

  private partnerCreated = (u: User): void => {
    this.setState({ addPartner: false, notice: `Partner ${u.email} created. They sign in at /login and land on the partner portal.`, role: 'partner', search: '', page: 1 });
    this.scheduleLoad();
  };

  private setPage = (page: number): void => {
    this.setState({ page });
  };

  public render(): React.ReactNode {
    const me = this.props.auth.user;
    const { data, page, search, role, error } = this.state;

    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2">
          <h1 className="h2 mb-0">Users</h1>
          <div className="d-flex align-items-center gap-3">
            {data && <span className="text-muted">{data.count} registered</span>}
            <button type="button" className="btn btn-outline-primary" onClick={() => this.setState({ addPartner: !this.state.addPartner, notice: '' })} aria-expanded={this.state.addPartner}>
              <i className="bi bi-briefcase me-1" aria-hidden="true" />Add partner
            </button>
            <div className="dropdown position-relative" ref={this.exportMenu}>
              <button
                type="button"
                className="btn btn-outline-primary dropdown-toggle"
                aria-expanded={this.state.exportOpen}
                disabled={this.state.exporting !== null || !data?.count}
                onClick={() => this.setState({ exportOpen: !this.state.exportOpen })}
              >
                <i className="bi bi-download me-1" aria-hidden="true" />
                {this.state.exporting ? `Preparing ${this.state.exporting.toUpperCase()}…` : 'Export'}
              </button>
              <div className={`dropdown-menu dropdown-menu-end shadow export-menu ${this.state.exportOpen ? 'show' : ''}`} style={{ right: 0, left: 'auto' }}>
                <div className="dropdown-header">{search || role ? 'Users matching the current filter' : 'All users'}</div>
                {EXPORTS.map((x) => (
                  <button key={x.kind} type="button" className="dropdown-item d-flex align-items-center gap-2" onClick={() => this.download(x.kind)}>
                    <i className={`bi ${x.icon} fs-5 text-primary`} aria-hidden="true" />
                    <span>
                      <span className="d-block fw-semibold">{x.label}</span>
                      <span className="d-block small text-muted">{x.hint}</span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
        <p className="text-muted small mb-4">Passwords are stored only as one-way Argon2 hashes and can't be viewed by anyone. Users change their own password from My profile.</p>
        <div className="card border-0 shadow-sm mb-3">
          <div className="card-body">
            <div className="row g-2">
              <div className="col-md-8">
                <input className="form-control" placeholder="Search by name, email, phone…" value={search} onChange={(e) => this.setState({ search: e.target.value, page: 1 })} />
              </div>
              <div className="col-md-4">
                <select className="form-select" value={role} onChange={(e) => this.setState({ role: e.target.value, page: 1 })}>
                  <option value="">All roles</option>
                  {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
              </div>
            </div>
          </div>
        </div>
        {this.state.addPartner && <NewPartnerForm onCreated={this.partnerCreated} onClose={() => this.setState({ addPartner: false })} />}
        {this.state.notice && <div className="alert alert-success py-2">{this.state.notice}</div>}
        {error && <div className="alert alert-danger">{error}</div>}

        {data === null ? (
          <Loader />
        ) : data.count === 0 ? (
          <Empty title="No users found" />
        ) : (
          <>
            <div className="card border-0 shadow-sm">
              <div className="table-responsive">
                <table className="table table-hover align-middle mb-0">
                  <thead className="table-light"><tr><th>Name</th><th>Email</th><th>Phone</th><th>Joined</th><th>Last login</th><th className="text-end">Bookings</th><th>Role</th><th>Active</th><th>Places</th></tr></thead>
                  <tbody>
                    {data.results.map((u) => {
                      const self = u.id === me?.id;
                      const open = this.state.museumsFor === u.id;
                      return (
                        <React.Fragment key={u.id}>
                        <tr>
                          <td>{`${u.first_name} ${u.last_name}`.trim() || '—'}</td>
                          <td>{u.email}</td>
                          <td>{u.phone || '—'}</td>
                          <td>{formatDate(u.date_joined)}</td>
                          <td className="text-muted small">{u.last_login ? formatDateTime(u.last_login) : 'Never'}</td>
                          <td className="text-end">{u.booking_count ?? 0}</td>
                          <td>
                            <select className="form-select form-select-sm w-auto" value={u.role} disabled={self} onChange={(e) => this.update(u, { role: e.target.value as Role })}>
                              {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                            </select>
                          </td>
                          <td>
                            <div className="form-check form-switch mb-0">
                              <input className="form-check-input" type="checkbox" checked={u.is_active} disabled={self} onChange={() => this.update(u, { is_active: !u.is_active })} aria-label="Active" />
                            </div>
                          </td>
                          <td>
                            {u.role === 'staff' || u.role === 'partner' ? (
                              <button
                                type="button"
                                className={`btn btn-sm ${open ? 'btn-primary' : 'btn-outline-primary'}`}
                                aria-expanded={open}
                                onClick={() => this.setState({ museumsFor: open ? null : u.id })}
                              >
                                <i className="bi bi-building me-1" aria-hidden="true" />Museums
                              </button>
                            ) : (
                              <span className="text-muted small">{u.role === 'admin' ? 'All' : '—'}</span>
                            )}
                          </td>
                        </tr>
                        {open && (u.role === 'staff' || u.role === 'partner') && (
                          <tr>
                            <td colSpan={9} className="bg-light">
                              <StaffMuseumsPanel key={`${u.id}-${u.role}`} user={u} kind={u.role === 'partner' ? 'partner' : 'staff'} onClose={() => this.setState({ museumsFor: null })} />
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
              <Pagination page={page} count={data.count} onChange={this.setPage} />
            </div>
          </>
        )}
      </div>
    );
  }
}

export default withAuth(AdminUsersPage);
