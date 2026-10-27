import * as React from 'react';
import { api, errorMessage } from '../../api/client';
import type { Gate, Occupancy as OccupancyData } from '../../api/passes';
import { Loader } from '../../components/Common';
import MuseumPicker from '../../components/MuseumPicker';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { formatDateTime, formatTime } from '../../utils/format';
import { gateMuseum } from '../../utils/gateMuseum';

/** Live occupancy of one place today: expected vs entered per slot and per gate. Refreshes every 30 seconds. */

const REFRESH_MS = 30_000;

type OccupancyProps = WithAuthProps;

interface OccupancyState {
  slug: string;
  data: OccupancyData | null;
  loading: boolean;
  error: string;
  gates: Gate[];
  newGate: string;
  gateError: string;
  gateBusy: boolean;
}

const pctClass = (pct: number) => (pct >= 90 ? 'bg-danger' : pct >= 70 ? 'bg-warning' : 'bg-success');

class Occupancy extends React.Component<OccupancyProps, OccupancyState> {
  public state: OccupancyState = {
    slug: gateMuseum.get(), data: null, loading: false, error: '', gates: [], newGate: '', gateError: '', gateBusy: false,
  };

  private mounted = false;
  private timer: ReturnType<typeof setInterval> | undefined;

  public componentDidMount(): void {
    this.mounted = true;
    this.refresh();
    this.loadGates();
    this.timer = setInterval(() => {
      if (document.visibilityState !== 'hidden') this.refresh();
    }, REFRESH_MS);
  }

  public componentDidUpdate(_p: OccupancyProps, prev: OccupancyState): void {
    if (prev.slug !== this.state.slug) {
      this.setState({ data: null });
      this.refresh();
      this.loadGates();
    }
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearInterval(this.timer);
  }

  private refresh = async (): Promise<void> => {
    const { slug } = this.state;
    if (!slug) return;
    this.setState({ loading: true });
    try {
      const { data } = await api.get<OccupancyData>('/admin/occupancy/', { params: { museum: slug } });
      if (this.mounted && data.museum === this.state.slug) this.setState({ data, error: '' });
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ loading: false });
    }
  };

  private loadGates = async (): Promise<void> => {
    const { slug } = this.state;
    if (!slug) return;
    try {
      const { data } = await api.get<Gate[]>('/admin/gates/', { params: { museum: slug } });
      if (this.mounted) this.setState({ gates: data });
    } catch {
      if (this.mounted) this.setState({ gates: [] });
    }
  };

  private onMuseumChange = (slug: string): void => {
    gateMuseum.set(slug);
    this.setState({ slug, error: '' });
  };

  private addGate = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const name = this.state.newGate.trim();
    if (!name) return;
    this.setState({ gateBusy: true, gateError: '' });
    try {
      await api.post('/admin/gates/', { museum: this.state.slug, name, sort_order: this.state.gates.length });
      if (!this.mounted) return;
      this.setState({ newGate: '' });
      this.loadGates();
      this.refresh();
    } catch (err) {
      if (this.mounted) this.setState({ gateError: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ gateBusy: false });
    }
  };

  private toggleGate = async (g: Gate): Promise<void> => {
    try {
      await api.patch(`/admin/gates/${g.id}/`, { is_active: !g.is_active });
      this.loadGates();
      this.refresh();
    } catch (err) {
      if (this.mounted) this.setState({ gateError: errorMessage(err) });
    }
  };

  private renderTiles(d: OccupancyData): React.ReactNode {
    const t = d.totals;
    const tiles = [
      { label: 'Expected today', value: t.expected, sub: t.pass_expected ? `incl. ${t.pass_expected} on combo passes` : 'paid tickets', icon: 'bi-people' },
      { label: 'Entered', value: t.entered, sub: t.expected ? `${t.entered_pct}% of expected` : 'no tickets yet', icon: 'bi-door-open' },
      {
        label: 'Inside now (estimate)',
        value: t.inside_estimate ?? '—',
        sub: t.inside_capacity ? `${t.inside_pct}% of ${t.inside_capacity} capacity` : d.is_today ? 'outside opening slots' : 'only for today',
        icon: 'bi-person-check',
        pct: t.inside_capacity ? t.inside_pct : null,
      },
      { label: 'Capacity today', value: t.capacity_today, sub: `${d.slots.length} slot${d.slots.length === 1 ? '' : 's'}`, icon: 'bi-bar-chart' },
    ];
    return (
      <div className="row g-3 mb-3">
        {tiles.map((tile) => (
          <div key={tile.label} className="col-sm-6 col-xl-3">
            <div className="card border-0 shadow-sm stat-card h-100">
              <div className="card-body">
                <div className="d-flex justify-content-between align-items-start">
                  <div className="text-muted small">{tile.label}</div>
                  <i className={`bi ${tile.icon} text-accent`} aria-hidden="true" />
                </div>
                <div className="stat-value">{tile.value}</div>
                <div className="text-muted small">{tile.sub}</div>
                {'pct' in tile && tile.pct !== null && tile.pct !== undefined && (
                  <div className="progress mt-2" style={{ height: 6 }} role="progressbar" aria-label="Estimated occupancy" aria-valuenow={tile.pct} aria-valuemin={0} aria-valuemax={100}>
                    <div className={`progress-bar ${pctClass(tile.pct)}`} style={{ width: `${Math.min(tile.pct, 100)}%` }} />
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    );
  }

  private renderSlots(d: OccupancyData): React.ReactNode {
    const gateCols = d.gates;
    return (
      <div className="card border-0 shadow-sm mb-4">
        <div className="card-header bg-white py-3"><h2 className="h5 mb-0">By slot</h2></div>
        <div className="table-responsive">
          <table className="table table-hover align-middle mb-0">
            <thead className="table-light">
              <tr>
                <th>Slot</th>
                <th className="text-end">Capacity</th>
                <th className="text-end">Expected</th>
                <th className="text-end">Entered</th>
                {gateCols.map((g) => <th key={String(g.gate_id)} className="text-end">{g.name}</th>)}
                <th style={{ minWidth: 140 }}>Booked</th>
              </tr>
            </thead>
            <tbody>
              {d.slots.map((s) => (
                <tr key={s.slot_id} className={s.is_current ? 'table-primary' : undefined}>
                  <td className="text-nowrap">
                    {formatTime(s.start)}–{formatTime(s.end)}
                    {s.is_current && <span className="badge bg-primary ms-2">Now</span>}
                    {s.counted_inside && !s.is_current && <span className="badge bg-light text-dark ms-2">Counted inside</span>}
                  </td>
                  <td className="text-end">{s.capacity}</td>
                  <td className="text-end">{s.expected}</td>
                  <td className="text-end">
                    {s.entered}
                    {s.pass_entered > 0 && <div className="small text-muted">{s.pass_entered} on passes</div>}
                  </td>
                  {gateCols.map((g) => (
                    <td key={String(g.gate_id)} className="text-end">
                      {s.by_gate.find((b) => b.gate_id === g.gate_id)?.entered ?? 0}
                    </td>
                  ))}
                  <td>
                    <div className="progress" style={{ height: 8 }} role="progressbar" aria-label={`Booked ${s.booked_pct}%`} aria-valuenow={s.booked_pct} aria-valuemin={0} aria-valuemax={100}>
                      <div className={`progress-bar ${pctClass(s.booked_pct)}`} style={{ width: `${Math.min(s.booked_pct, 100)}%` }} />
                    </div>
                    <div className="small text-muted">{s.booked_pct}%</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  private renderGates(d: OccupancyData): React.ReactNode {
    const isAdmin = !!this.props.auth.user?.is_admin_role;
    const { gates, newGate, gateError, gateBusy } = this.state;
    return (
      <div className="card border-0 shadow-sm mb-4">
        <div className="card-header bg-white py-3"><h2 className="h5 mb-0">By gate</h2></div>
        {d.gates.length === 0 ? (
          <div className="card-body text-muted small">No entries yet today.</div>
        ) : (
          <div className="table-responsive">
            <table className="table align-middle mb-0">
              <thead className="table-light">
                <tr><th>Gate</th><th className="text-end">Entered today</th><th className="text-end">Inside now (est.)</th><th>Status</th></tr>
              </thead>
              <tbody>
                {d.gates.map((g) => (
                  <tr key={String(g.gate_id)}>
                    <td>{g.gate_id === null ? <span className="text-muted">Not recorded</span> : g.name}</td>
                    <td className="text-end">{g.entered}</td>
                    <td className="text-end">{d.is_today ? g.inside_estimate : '—'}</td>
                    <td>{g.gate_id === null ? '' : <span className={`badge ${g.is_active ? 'bg-success' : 'bg-secondary'}`}>{g.is_active ? 'Open' : 'Closed'}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {isAdmin && (
          <div className="card-footer bg-white">
            <div className="small fw-semibold mb-2">Manage gates</div>
            {gateError && <div className="alert alert-danger py-2 small">{gateError}</div>}
            <div className="d-flex flex-wrap gap-2 mb-2">
              {gates.map((g) => (
                <button key={g.id} type="button" className={`btn btn-sm ${g.is_active ? 'btn-outline-success' : 'btn-outline-secondary'}`} onClick={() => this.toggleGate(g)} title={g.is_active ? 'Click to close this gate' : 'Click to reopen this gate'}>
                  <i className={`bi ${g.is_active ? 'bi-door-open' : 'bi-door-closed'} me-1`} aria-hidden="true" />
                  {g.name}
                </button>
              ))}
              {gates.length === 0 && <span className="text-muted small">No gates set up: scans are recorded without a gate.</span>}
            </div>
            <form className="d-flex gap-2" onSubmit={this.addGate} style={{ maxWidth: 420 }}>
              <input className="form-control form-control-sm" placeholder="New gate name, e.g. East gate" aria-label="New gate name" value={newGate} onChange={(e) => this.setState({ newGate: e.target.value })} maxLength={60} />
              <button className="btn btn-sm btn-primary text-nowrap" disabled={gateBusy || !newGate.trim()}>
                <i className="bi bi-plus-circle me-1" aria-hidden="true" /> Add gate
              </button>
            </form>
          </div>
        )}
      </div>
    );
  }

  public render(): React.ReactNode {
    const { slug, data, loading, error } = this.state;
    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-4">
          <h1 className="h2 mb-0">Live occupancy</h1>
          <div className="d-flex align-items-center gap-2 small text-muted">
            {data && <span>Updated {formatDateTime(data.generated_at)} · refreshes every 30 s</span>}
            <button className="btn btn-sm btn-outline-primary" onClick={this.refresh} disabled={loading || !slug} aria-label="Refresh now">
              <i className={`bi bi-arrow-clockwise ${loading ? 'opacity-50' : ''}`} aria-hidden="true" />
            </button>
          </div>
        </div>
        <div className="card border-0 shadow-sm mb-4" style={{ maxWidth: 520 }}>
          <div className="card-body">
            <MuseumPicker value={slug} onChange={this.onMuseumChange} />
          </div>
        </div>
        {error && <div className="alert alert-danger" role="alert">{error}</div>}
        {slug && !data && !error && <Loader />}
        {data && (
          <>
            {this.renderTiles(data)}
            <p className="small text-muted mb-4">
              <i className="bi bi-info-circle me-1" aria-hidden="true" />
              {data.estimate_note}
            </p>
            {this.renderSlots(data)}
            {this.renderGates(data)}
          </>
        )}
      </div>
    );
  }
}

export default withAuth(Occupancy);
