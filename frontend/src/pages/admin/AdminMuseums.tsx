import * as React from 'react';
import { Link } from 'react-router-dom';
import { clearApiCache } from '../../api/cache';
import { api, errorMessage } from '../../api/client';
import type { ImportResult, MuseumSummary, Paginated, State } from '../../api/types';
import { Empty, Loader, Pagination } from '../../components/Common';
import { PLACE_TYPES, formatDate, formatPrice, formatTime, placeLabel } from '../../utils/format';

interface AdminMuseumsProps {}

interface AdminMuseumsState {
  data: Paginated<MuseumSummary> | null;
  states: State[];
  page: number;
  search: string;
  /** Selected state / UT filter (the `state` query param). */
  stateFilter: string;
  type: string;
  /** '' | 'true' | 'false' — timings & prices verified with the place. */
  verified: string;
  error: string;
  reload: number;
  importing: boolean;
  importResult: ImportResult | null;
}

class AdminMuseumsPage extends React.Component<AdminMuseumsProps, AdminMuseumsState> {
  public state: AdminMuseumsState = {
    data: null,
    states: [],
    page: 1,
    search: '',
    stateFilter: '',
    type: '',
    verified: '',
    error: '',
    reload: 0,
    importing: false,
    importResult: null,
  };

  private timer: ReturnType<typeof setTimeout> | undefined;
  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    api.get<State[]>('/states/').then((r) => {
      if (this.mounted) this.setState({ states: r.data });
    });
    this.scheduleLoad();
  }

  public componentDidUpdate(_prevProps: AdminMuseumsProps, prevState: AdminMuseumsState): void {
    const s = this.state;
    if (
      s.page !== prevState.page ||
      s.search !== prevState.search ||
      s.stateFilter !== prevState.stateFilter ||
      s.type !== prevState.type ||
      s.verified !== prevState.verified ||
      s.reload !== prevState.reload
    ) {
      this.scheduleLoad();
    }
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.timer);
  }

  private scheduleLoad(): void {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      const { page, search, stateFilter, type, verified } = this.state;
      api
        .get<Paginated<MuseumSummary>>('/museums/', {
          params: { page, search: search || undefined, state: stateFilter || undefined, type: type || undefined, verified: verified || undefined },
        })
        .then((r) => {
          if (this.mounted) this.setState({ data: r.data });
        });
    }, 250);
  }

  private bumpReload = (): void => {
    this.setState((s) => ({ reload: s.reload + 1 }));
  };

  private toggle = async (m: MuseumSummary, field: 'is_active' | 'is_featured' | 'allow_individual' | 'allow_groups'): Promise<void> => {
    try {
      await api.patch(`/museums/${m.slug}/`, { [field]: !(m[field] ?? true) });
      clearApiCache();
      this.bumpReload();
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    }
  };

  private onImport = async (e: React.ChangeEvent<HTMLInputElement>): Promise<void> => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    this.setState({ importing: true, error: '', importResult: null });
    try {
      const body = new FormData();
      body.append('file', file);
      const { data } = await api.post<ImportResult>('/museums/import/', body);
      this.setState({ importResult: data });
      clearApiCache();
      this.bumpReload();
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    } finally {
      this.setState({ importing: false });
    }
  };

  private remove = async (m: MuseumSummary): Promise<void> => {
    if (!confirm(`Delete ${m.name}? Museums with bookings can't be deleted; deactivate them instead.`)) return;
    try {
      await api.delete(`/museums/${m.slug}/`);
      clearApiCache();
      this.bumpReload();
    } catch {
      this.setState({ error: `${m.name} has bookings and can't be deleted. Deactivate it instead.` });
    }
  };

  private setPage = (page: number): void => {
    this.setState({ page });
  };

  public render(): React.ReactNode {
    const { data, states, page, search, stateFilter, type, verified, error, importing, importResult } = this.state;

    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-4">
          <h1 className="h2 mb-0">Places</h1>
          <div className="d-flex flex-wrap gap-2">
            <label className={`btn btn-outline-primary mb-0${importing ? ' disabled' : ''}`}>
              <i className="bi bi-upload me-1" aria-hidden="true" /> {importing ? 'Importing…' : 'Import CSV'}
              <input type="file" accept=".csv,text/csv" hidden disabled={importing} onChange={this.onImport} />
            </label>
            <Link to="/admin/museums/new" className="btn btn-accent">
              <i className="bi bi-plus-lg me-1" aria-hidden="true" /> Add place
            </Link>
          </div>
        </div>
        <details className="text-muted small mb-3">
          <summary style={{ cursor: 'pointer' }}>CSV format for bulk import</summary>
          <p className="mt-2 mb-0">
            Save from Excel as <strong>CSV UTF-8</strong>. Required columns: <code>name, city, state, category, operator</code>. Optional <code>type</code>: museum, fort, palace or monument.
            <code> state</code> is a code (MH) or full name. <code>operator</code> is one of asi, central, state, ncsm, trust,
            private, palace, defence, university, railway, asi_monument, state_monument, which sets default timings and prices.
            Optional: <code>tagline, description, address, opening_time, closing_time, closed_day, price_indian, price_foreign,
            price_student, price_child, slot_capacity, latitude, longitude, image_url, featured</code>.
            Museums that already exist (same name + city) are skipped.
          </p>
        </details>
        {importResult && (
          <div className={`alert ${importResult.errors.length ? 'alert-warning' : 'alert-success'}`}>
            Imported {importResult.created} new place{importResult.created === 1 ? '' : 's'}, skipped {importResult.skipped} existing.
            {importResult.errors.length > 0 && (
              <ul className="mt-2 mb-0 ps-3">
                {importResult.errors.slice(0, 20).map((e) => (
                  <li key={e.row}>Row {e.row}{e.name ? ` (${e.name})` : ''}: {e.error}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div className="card border-0 shadow-sm mb-3">
          <div className="card-body">
            <div className="row g-2">
              <div className="col-lg-5">
                <input className="form-control" placeholder="Search places…" value={search} onChange={(e) => this.setState({ search: e.target.value, page: 1 })} />
              </div>
              <div className="col-sm-6 col-lg-2">
                <select className="form-select" value={type} onChange={(e) => this.setState({ type: e.target.value, page: 1 })} aria-label="Type">
                  <option value="">All types</option>
                  {PLACE_TYPES.map((p) => <option key={p.value} value={p.value}>{p.plural}</option>)}
                </select>
              </div>
              <div className="col-sm-6 col-lg-3">
                <select className="form-select" value={stateFilter} onChange={(e) => this.setState({ stateFilter: e.target.value, page: 1 })}>
                  <option value="">All states / UTs</option>
                  {states.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </div>
              <div className="col-sm-6 col-lg-2">
                <select className="form-select" value={verified} onChange={(e) => this.setState({ verified: e.target.value, page: 1 })} aria-label="Verification">
                  <option value="">Any verification</option>
                  <option value="true">Verified</option>
                  <option value="false">Not verified</option>
                </select>
              </div>
            </div>
          </div>
        </div>
        {error && <div className="alert alert-danger">{error}</div>}

        {data === null ? (
          <Loader />
        ) : data.count === 0 ? (
          <Empty title="No places found" />
        ) : (
          <>
            <div className="card border-0 shadow-sm">
              <div className="table-responsive">
                <table className="table table-hover align-middle mb-0">
                  <thead className="table-light">
                    <tr><th>Name</th><th>Type</th><th>Location</th><th>Category</th><th>Timings</th><th className="text-end">From</th><th>Verified</th><th title="Individual online tickets">Individual</th><th title="Group bookings, group requests and school trips">Groups</th><th>Featured</th><th>Active</th><th /></tr>
                  </thead>
                  <tbody>
                    {data.results.map((m) => (
                      <tr key={m.id}>
                        <td><Link to={`/museums/${m.slug}`} target="_blank" className="fw-semibold text-decoration-none">{m.name}</Link></td>
                        <td>{placeLabel(m.place_type)}</td>
                        <td>{m.city_name}<div className="text-muted small">{m.state_name}</div></td>
                        <td>{m.category_name ?? '—'}</td>
                        <td className="small text-nowrap">{formatTime(m.opening_time)} – {formatTime(m.closing_time)}</td>
                        <td className="text-end">{m.starting_price === null ? '—' : formatPrice(m.starting_price)}</td>
                        <td>
                          {m.info_verified ? (
                            <span
                              className="badge bg-success"
                              title={`Verified${m.info_verified_by_name ? ` by ${m.info_verified_by_name}` : ''}${m.info_verified_at ? ` on ${formatDate(m.info_verified_at)}` : ''}`}
                            >
                              <i className="bi bi-patch-check-fill me-1" aria-hidden="true" />Verified
                            </span>
                          ) : (
                            <span className="badge bg-light text-muted border">Not verified</span>
                          )}
                        </td>
                        <td>
                          <div className="form-check form-switch mb-0">
                            <input className="form-check-input" type="checkbox" checked={m.allow_individual ?? true} onChange={() => this.toggle(m, 'allow_individual')} aria-label="Individual tickets" />
                          </div>
                        </td>
                        <td>
                          <div className="form-check form-switch mb-0">
                            <input className="form-check-input" type="checkbox" checked={m.allow_groups ?? true} onChange={() => this.toggle(m, 'allow_groups')} aria-label="Groups" />
                          </div>
                        </td>
                        <td>
                          <div className="form-check form-switch mb-0">
                            <input className="form-check-input" type="checkbox" checked={m.is_featured} onChange={() => this.toggle(m, 'is_featured')} aria-label="Featured" />
                          </div>
                        </td>
                        <td>
                          <div className="form-check form-switch mb-0">
                            <input className="form-check-input" type="checkbox" checked={m.is_active} onChange={() => this.toggle(m, 'is_active')} aria-label="Active" />
                          </div>
                        </td>
                        <td className="text-end">
                          <div className="d-flex flex-nowrap gap-1 justify-content-end">
                            <Link to={`/admin/museums/${m.slug}/edit`} className="btn btn-sm btn-light">
                              <i className="bi bi-pencil me-1" aria-hidden="true" />Edit
                            </Link>
                            <button className="btn btn-sm btn-outline-danger" onClick={() => this.remove(m)}>
                              <i className="bi bi-trash me-1" aria-hidden="true" />Delete
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
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

export default AdminMuseumsPage;
