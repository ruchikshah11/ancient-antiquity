import * as React from 'react';
import type { FunnelDay, FunnelReport, FunnelStep } from '../../api/analytics';
import { api, errorMessage } from '../../api/client';
import { Loader } from '../../components/Common';
import MuseumPicker from '../../components/MuseumPicker';
import { formatDate, formatNumber, isoDate } from '../../utils/format';
import { DayTick, tickEvery } from '../../components/DayTick';

/*
 * Booking funnel (admin/staff): visitor sessions from page tracking, then bookings from the bookings table.
 * One hue (the brand primary) for every bar: the bars encode magnitude of one measure, not identity.
 */

const BAR = '#0277bd';
const TRACK = '#e0f2fe';

const RANGES = [
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
];

const pct = (v: number | null | undefined): string => (v === null || v === undefined ? '—' : `${v}%`);

interface TileProps {
  label: string;
  value: string;
  sub: string;
  icon: string;
}

class Tile extends React.Component<TileProps> {
  public render(): React.ReactNode {
    const { label, value, sub, icon } = this.props;
    return (
      <div className="card border-0 shadow-sm stat-card h-100">
        <div className="card-body">
          <div className="d-flex justify-content-between align-items-start">
            <div className="text-muted small">{label}</div>
            <i className={`bi ${icon} text-accent`} aria-hidden="true" />
          </div>
          <div className="stat-value">{value}</div>
          <div className="text-muted small">{sub}</div>
        </div>
      </div>
    );
  }
}

interface FunnelChartProps {
  steps: FunnelStep[];
}

/** Horizontal funnel: one bar per step, width relative to the first step, value labelled at the bar end. */
class FunnelChart extends React.Component<FunnelChartProps> {
  public render(): React.ReactNode {
    const { steps } = this.props;
    const max = Math.max(1, ...steps.map((s) => s.count));
    return (
      <div role="list" aria-label="Booking funnel steps" data-testid="funnel-chart">
        {steps.map((s, i) => {
          const width = (s.count / max) * 100;
          const tip = `${s.label}: ${formatNumber(s.count)} ${s.source}${s.pct_of_previous !== null ? ` · ${pct(s.pct_of_previous)} of previous step` : ''}`;
          return (
            <div key={s.key} role="listitem" className="mb-2" title={tip} tabIndex={0} aria-label={tip}>
              <div className="d-flex justify-content-between small mb-1">
                <span>
                  {s.label}
                  <span className="text-muted ms-1">({s.source})</span>
                </span>
                {i > 0 && <span className="text-muted">{pct(s.pct_of_previous)} of previous</span>}
              </div>
              <div className="d-flex align-items-center gap-2" aria-hidden="true">
                <div className="flex-grow-1" style={{ background: TRACK, borderRadius: 4, height: 22 }}>
                  <div
                    style={{
                      width: `${Math.max(width, s.count > 0 ? 0.5 : 0)}%`, height: '100%', background: BAR,
                      borderRadius: '0 4px 4px 0', transition: 'width .3s',
                    }}
                  />
                </div>
                <span className="fw-semibold text-end" style={{ minWidth: 64 }}>{formatNumber(s.count)}</span>
              </div>
            </div>
          );
        })}
      </div>
    );
  }
}

interface TrendProps {
  data: FunnelDay[];
}

/** Daily place views (sessions) as single-hue columns; started/paid counts in the tooltip and table. */
class Trend extends React.Component<TrendProps> {
  public render(): React.ReactNode {
    const { data } = this.props;
    const max = Math.max(1, ...data.map((d) => d.views));
    const every = tickEvery(data.length);
    return (
      <div className="chart-bars" role="img" aria-label={`Place views per day, ${data.length} days`}>
        {data.map((d, i) => (
          <div className="col-bar" key={d.date} tabIndex={0}>
            <span className="tip">
              {formatDate(d.date, { day: 'numeric', month: 'short' })}: {d.views} views · {d.started} started · {d.paid} paid
            </span>
            <div className="bar" style={{ height: `${(d.views / max) * 100}%` }} />
            <DayTick dates={data.map((x) => x.date)} index={i} every={every} />
          </div>
        ))}
      </div>
    );
  }
}

interface FunnelState {
  from: string;
  to: string;
  museum: string;
  data: FunnelReport | null;
  loading: boolean;
  error: string;
  showTable: boolean;
}

export default class Funnel extends React.Component<Record<string, never>, FunnelState> {
  public state: FunnelState = {
    from: isoDate(-29), to: isoDate(0), museum: '', data: null, loading: true, error: '', showTable: false,
  };

  private mounted = false;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private requestId = 0;

  public componentDidMount(): void {
    this.mounted = true;
    this.scheduleLoad();
  }

  public componentDidUpdate(_p: Record<string, never>, prev: FunnelState): void {
    const s = this.state;
    if (s.from !== prev.from || s.to !== prev.to || s.museum !== prev.museum) this.scheduleLoad();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.timer);
  }

  private scheduleLoad(): void {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.load(), 250);
  }

  private load(): void {
    const { from, to, museum } = this.state;
    if (!from || !to) return;
    const id = ++this.requestId;
    const alive = (): boolean => this.mounted && id === this.requestId;
    this.setState({ loading: true, error: '' });
    api
      .get<FunnelReport>('/admin/funnel/', { params: { from, to, museum: museum || undefined } })
      .then((r) => alive() && this.setState({ data: r.data, loading: false }))
      .catch((err) => alive() && this.setState({ data: null, loading: false, error: errorMessage(err) }));
  }

  private renderTable(steps: FunnelStep[]): React.ReactNode {
    return (
      <div className="table-responsive">
        <table className="table table-sm align-middle mb-0" data-testid="funnel-table">
          <caption className="visually-hidden">Booking funnel steps</caption>
          <thead className="table-light">
            <tr>
              <th scope="col">Step</th>
              <th scope="col">Counts</th>
              <th scope="col" className="text-end">Count</th>
              <th scope="col" className="text-end">% of previous</th>
              <th scope="col" className="text-end">% of first</th>
            </tr>
          </thead>
          <tbody>
            {steps.map((s) => (
              <tr key={s.key}>
                <th scope="row" className="fw-normal">{s.label}</th>
                <td className="text-muted">{s.source}</td>
                <td className="text-end">{formatNumber(s.count)}</td>
                <td className="text-end">{pct(s.pct_of_previous)}</td>
                <td className="text-end">{pct(s.pct_of_first)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  public render(): React.ReactNode {
    const { from, to, museum, data, loading, error, showTable } = this.state;
    const views = data?.steps[0]?.count ?? 0;
    const paid = data?.steps[data.steps.length - 1]?.count ?? 0;

    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-4">
          <h1 className="h2 mb-0">Booking funnel</h1>
        </div>

        <div className="card border-0 shadow-sm mb-3">
          <div className="card-body">
            <div className="row g-3 align-items-start">
              <div className="col-sm-6 col-lg-3">
                <label htmlFor="fun-from" className="form-label">From</label>
                <input id="fun-from" type="date" className="form-control" value={from} max={to} onChange={(e) => this.setState({ from: e.target.value })} />
              </div>
              <div className="col-sm-6 col-lg-3">
                <label htmlFor="fun-to" className="form-label">To</label>
                <input id="fun-to" type="date" className="form-control" value={to} min={from} onChange={(e) => this.setState({ to: e.target.value })} />
                <div className="d-flex gap-2 mt-1">
                  {RANGES.map((r) => (
                    <button key={r.days} type="button" className="btn btn-link btn-sm p-0" onClick={() => this.setState({ from: isoDate(-(r.days - 1)), to: isoDate(0) })}>
                      Last {r.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="col-lg-6">
                <MuseumPicker label="Place (leave empty for all your places)" value={museum} clearable onChange={(slug) => this.setState({ museum: slug })} />
              </div>
            </div>
            <p className="text-muted small mb-0 mt-2">
              Session steps count visitor browser sessions (staff and bots excluded). Booking steps count online, non-group
              bookings created in the period; &quot;Paid&quot; includes bookings later cancelled.
            </p>
          </div>
        </div>

        {error && <div className="alert alert-danger">{error}</div>}

        {loading && !data ? (
          <Loader />
        ) : data ? (
          <div style={{ opacity: loading ? 0.6 : 1 }}>
            <div className="row g-3 mb-4">
              <div className="col-sm-6 col-xl-3">
                <Tile label="Place views" value={formatNumber(views)} sub="Visitor sessions" icon="bi-eye" />
              </div>
              <div className="col-sm-6 col-xl-3">
                <Tile label="Paid bookings" value={formatNumber(paid)} sub={`${pct(data.overall_conversion)} of sessions`} icon="bi-check-circle" />
              </div>
              <div className="col-sm-6 col-xl-3">
                <Tile label="Abandoned / cancelled" value={`${formatNumber(data.abandoned)} / ${formatNumber(data.cancelled)}`} sub="Unpaid holds expired · cancelled" icon="bi-x-circle" />
              </div>
              <div className="col-sm-6 col-xl-3">
                <Tile
                  label="Recovery emails"
                  value={formatNumber(data.recovery.sent)}
                  sub={`${formatNumber(data.recovery.converted)} converted (${pct(data.recovery.conversion)}) within 7 days`}
                  icon="bi-envelope"
                />
              </div>
            </div>

            <div className="card border-0 shadow-sm mb-4">
              <div className="card-body">
                <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3">
                  <h2 className="h4 mb-0">Funnel</h2>
                  <div className="d-flex align-items-center gap-3">
                    <span className="text-muted small">
                      {formatDate(data.from)} – {formatDate(data.to)}{data.museum ? ` · ${data.museum.name}` : ''}
                    </span>
                    <button
                      type="button"
                      className="btn btn-outline-secondary btn-sm"
                      aria-pressed={showTable}
                      onClick={() => this.setState({ showTable: !showTable })}
                    >
                      <i className={`bi ${showTable ? 'bi-bar-chart' : 'bi-table'} me-1`} aria-hidden="true" />
                      {showTable ? 'Show chart' : 'Show table'}
                    </button>
                  </div>
                </div>
                {showTable ? this.renderTable(data.steps) : <FunnelChart steps={data.steps} />}
              </div>
            </div>

            <div className="row g-4 mb-4">
              <div className="col-lg-7">
                <div className="card border-0 shadow-sm h-100">
                  <div className="card-body">
                    <h2 className="h5">Place views per day</h2>
                    <Trend data={data.daily} />
                  </div>
                </div>
              </div>
              <div className="col-lg-5">
                <div className="card border-0 shadow-sm h-100">
                  <div className="card-body">
                    <h2 className="h5">Top places by conversion</h2>
                    {data.top_places.length === 0 ? (
                      <p className="text-muted small mb-0">No place views or online bookings in this period.</p>
                    ) : (
                      <div className="table-responsive">
                        <table className="table table-sm align-middle mb-0">
                          <thead className="table-light">
                            <tr>
                              <th scope="col">Place</th>
                              <th scope="col" className="text-end">Views</th>
                              <th scope="col" className="text-end">Paid</th>
                              <th scope="col" className="text-end">Conversion</th>
                            </tr>
                          </thead>
                          <tbody>
                            {data.top_places.map((p) => (
                              <tr key={p.slug}>
                                <td>
                                  {p.name}
                                  <div className="text-muted small">{p.city}</div>
                                </td>
                                <td className="text-end">{formatNumber(p.views)}</td>
                                <td className="text-end">{formatNumber(p.paid)}</td>
                                <td className="text-end">{pct(p.conversion)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    );
  }
}
