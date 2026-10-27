import * as React from 'react';
import { errorMessage } from '../../api/client';
import { createPriceRule, getPricingSuggestions } from '../../api/insights';
import type { PricingCell, PricingInsights as PricingData, PricingSuggestion } from '../../api/types';
import { Empty, Loader } from '../../components/Common';
import MuseumPicker from '../../components/MuseumPicker';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { formatDate, formatINR, formatTime } from '../../utils/format';

/** Fill-rate bands of the heat map (share of slot capacity used on an average open day). */
const BANDS: { upTo: number; color: string; label: string }[] = [
  { upTo: 0.25, color: '#cfe2ff', label: 'under 25%' },
  { upTo: 0.5, color: '#d1e7dd', label: '25–50%' },
  { upTo: 0.7, color: '#fff3cd', label: '50–70%' },
  { upTo: 0.85, color: '#ffd8a8', label: '70–85%' },
  { upTo: Infinity, color: '#f5b5bb', label: '85% and over' },
];

const bandColor = (fill: number): string => (BANDS.find((b) => fill < b.upTo) ?? BANDS[BANDS.length - 1]).color;
const pct = (v: number | null | undefined): string => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`);
const signed = (n: number): string => `${n > 0 ? '+' : ''}${n}%`;
const money = (n: number): string => `${n > 0 ? '+' : n < 0 ? '−' : ''}${formatINR(Math.abs(n))}`;

const WEEK_OPTIONS = [4, 8, 12, 26];

interface Props extends WithAuthProps {}

interface State {
  museum: string;
  museumName: string;
  weeks: number;
  elasticity: number;
  data: PricingData | null;
  loading: boolean;
  error: string;
  /** suggestion key -> 'saving' | 'done' | error message */
  ruleState: Record<string, string>;
}

const keyOf = (s: PricingSuggestion): string => `${s.weekday}-${s.kind}`;

/** Admin -> Pricing insights: weekday x slot fill rates and price-rule suggestions for one place. */
class PricingInsightsPage extends React.Component<Props, State> {
  public state: State = { museum: '', museumName: '', weeks: 12, elasticity: 0.5, data: null, loading: false, error: '', ruleState: {} };

  private mounted = false;
  private timer: ReturnType<typeof setTimeout> | undefined;

  public componentDidMount(): void {
    this.mounted = true;
  }

  public componentDidUpdate(_p: Props, prev: State): void {
    const s = this.state;
    if (s.museum !== prev.museum || s.weeks !== prev.weeks || s.elasticity !== prev.elasticity) {
      clearTimeout(this.timer);
      this.timer = setTimeout(this.load, 250);
    }
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.timer);
  }

  private load = (): void => {
    const { museum, weeks, elasticity } = this.state;
    if (!museum) {
      this.setState({ data: null, error: '' });
      return;
    }
    this.setState({ loading: true, error: '' });
    getPricingSuggestions(museum, weeks, elasticity)
      .then((data) => this.mounted && this.state.museum === museum && this.setState({ data, loading: false, ruleState: {} }))
      .catch((err) => this.mounted && this.setState({ error: errorMessage(err), loading: false, data: null }));
  };

  private createRule = async (s: PricingSuggestion): Promise<void> => {
    const key = keyOf(s);
    this.setState((st) => ({ ruleState: { ...st.ruleState, [key]: 'saving' } }));
    try {
      await createPriceRule(s.rule);
      if (this.mounted) this.setState((st) => ({ ruleState: { ...st.ruleState, [key]: 'done' } }));
    } catch (err) {
      if (this.mounted) this.setState((st) => ({ ruleState: { ...st.ruleState, [key]: errorMessage(err) } }));
    }
  };

  private renderCell(cell: PricingCell, minDays: number): React.ReactNode {
    if (cell.status === 'closed') {
      return <td key={cell.slot} className="text-center text-muted small" style={{ background: '#f1f3f5' }}>closed</td>;
    }
    const title = `${pct(cell.fill)} full on average over ${cell.days} open day${cell.days === 1 ? '' : 's'} · ${cell.visitors} visitors · `
      + `${cell.busy_days} busy, ${cell.quiet_days} quiet days`
      + (cell.status === 'nodata' ? ` · fewer than ${minDays} open days, no suggestion` : '');
    return (
      <td key={cell.slot} className="text-center small" style={{ background: bandColor(cell.fill ?? 0) }} title={title}>
        <span className="fw-semibold">{pct(cell.fill)}</span>
        {cell.status === 'busy' && <span className="d-block text-danger"><i className="bi bi-arrow-up-circle me-1" aria-hidden="true" />{signed(cell.suggested_percent)}</span>}
        {cell.status === 'quiet' && <span className="d-block text-primary"><i className="bi bi-arrow-down-circle me-1" aria-hidden="true" />{signed(cell.suggested_percent)}</span>}
      </td>
    );
  }

  private renderGrid(data: PricingData): React.ReactNode {
    return (
      <div className="card border-0 shadow-sm mb-4">
        <div className="card-body">
          <h2 className="h5 mb-1">How full each slot was</h2>
          <p className="text-muted small mb-3">
            Average share of capacity used on open days, {formatDate(data.from)} to {formatDate(data.to)} ({data.weeks} weeks). Closed days and
            closed slots are left out; open days with no bookings count as 0%. Arrows mark slots that were consistently busy (≥ {pct(data.thresholds.busy_fill)} full
            on at least {pct(data.thresholds.consistent_share)} of days) or quiet (≤ {pct(data.thresholds.quiet_fill)}).
          </p>
          <div className="table-responsive">
            <table className="table table-bordered table-sm align-middle mb-2">
              <caption className="visually-hidden">Fill rate by weekday and slot</caption>
              <thead className="table-light">
                <tr>
                  <th scope="col">Day</th>
                  {data.slots.map((s) => (
                    <th scope="col" key={s.id} className="text-center small">
                      {formatTime(s.start_time)}–{formatTime(s.end_time)}
                      <span className="d-block text-muted fw-normal">cap. {s.capacity}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.grid.map((row) => (
                  <tr key={row.weekday}>
                    <th scope="row" className="small">{row.label}</th>
                    {row.cells.map((c) => this.renderCell(c, data.thresholds.min_days))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="d-flex flex-wrap gap-3 small text-muted" aria-label="Colour legend">
            {BANDS.map((b) => (
              <span key={b.label} className="d-inline-flex align-items-center gap-1">
                <span style={{ width: 14, height: 14, background: b.color, borderRadius: 3, display: 'inline-block' }} aria-hidden="true" />
                {b.label}
              </span>
            ))}
          </div>
        </div>
      </div>
    );
  }

  private renderSuggestion(s: PricingSuggestion, data: PricingData): React.ReactNode {
    const key = keyOf(s);
    const state = this.state.ruleState[key];
    const slotLabel = (id: number): string => {
      const slot = data.slots.find((x) => x.id === id);
      return slot ? formatTime(slot.start_time) : String(id);
    };
    const premium = s.kind === 'premium';
    return (
      <div key={key} className="list-group-item py-3">
        <div className="d-flex justify-content-between align-items-start flex-wrap gap-2">
          <div>
            <div className="fw-semibold">
              <span className={`badge me-2 ${premium ? 'bg-danger' : 'bg-primary'}`}>{premium ? 'Premium' : 'Discount'} {signed(s.percent)}</span>
              {s.weekday_label}s
            </div>
            <div className="small text-muted mt-1">
              {premium ? 'Consistently busy' : 'Consistently quiet'}: {s.slots.map((x) => `${slotLabel(x.slot)} (${pct(x.fill)})`).join(', ')}
              {!s.all_slots && ' · a price rule covers the whole day, so the other slots change too'}
            </div>
            {s.conflict && (
              <div className="small text-warning-emphasis mt-1">
                <i className="bi bi-exclamation-triangle me-1" aria-hidden="true" />
                This day has both busy and quiet slots; one whole-day rule can&apos;t suit both.
              </div>
            )}
            <div className="small mt-2">
              Estimated per {s.weekday_label}: visitors {s.visitors_per_week.current} → {s.visitors_per_week.estimated}, ticket revenue{' '}
              {formatINR(s.revenue_per_week.current)} → {formatINR(s.revenue_per_week.estimated)}{' '}
              <strong className={s.revenue_per_week.change >= 0 ? 'text-success' : 'text-danger'}>({money(s.revenue_per_week.change)} a week</strong>
              <strong className={s.revenue_change_over_period >= 0 ? 'text-success' : 'text-danger'}>, {money(s.revenue_change_over_period)} over {data.weeks} weeks)</strong>
            </div>
          </div>
          <div className="text-end">
            {state === 'done' ? (
              <span className="text-success small"><i className="bi bi-check2-circle me-1" aria-hidden="true" />Rule created ({s.rule.start_date} to {s.rule.end_date})</span>
            ) : data.can_create_rules ? (
              <button type="button" className="btn btn-sm btn-outline-primary" disabled={state === 'saving'} onClick={() => this.createRule(s)}>
                <i className="bi bi-plus-circle me-1" aria-hidden="true" />{state === 'saving' ? 'Creating…' : 'Create price rule'}
              </button>
            ) : (
              <span className="text-muted small">Ask an administrator to create the rule.</span>
            )}
            {state && state !== 'saving' && state !== 'done' && <div className="text-danger small mt-1">{state}</div>}
          </div>
        </div>
      </div>
    );
  }

  public render(): React.ReactNode {
    const { museum, weeks, elasticity, data, loading, error } = this.state;
    return (
      <div>
        <h1 className="h2 mb-1">Pricing insights</h1>
        <p className="text-muted small mb-4">
          Suggested premiums for consistently busy slots and discounts for quiet ones, from the last weeks of bookings. Suggestions only: nothing changes until you create a rule.
        </p>
        <div className="card border-0 shadow-sm mb-3">
          <div className="card-body">
            <div className="row g-2 align-items-end">
              <div className="col-md-6">
                <MuseumPicker filter label="Place" value={museum} onChange={(slug, name) => this.setState({ museum: slug, museumName: name })} />
              </div>
              <div className="col-6 col-md-3">
                <label htmlFor="pi-weeks" className="form-label small mb-1">Look back</label>
                <select id="pi-weeks" className="form-select" value={weeks} onChange={(e) => this.setState({ weeks: Number(e.target.value) })}>
                  {WEEK_OPTIONS.map((w) => <option key={w} value={w}>{w} weeks</option>)}
                </select>
              </div>
              <div className="col-6 col-md-3">
                <label htmlFor="pi-elasticity" className="form-label small mb-1">Price elasticity (assumption)</label>
                <input
                  id="pi-elasticity" type="number" className="form-control" min={0} max={3} step={0.1} value={elasticity}
                  onChange={(e) => this.setState({ elasticity: Math.min(3, Math.max(0, Number(e.target.value) || 0)) })}
                  aria-describedby="pi-elasticity-help"
                />
              </div>
            </div>
            <div id="pi-elasticity-help" className="form-text">
              {elasticity === 0
                ? 'Elasticity 0: assumes visitor numbers do not react to price at all.'
                : `Elasticity ${elasticity}: assumes a 10% price rise loses ${+(elasticity * 10).toFixed(1)}% of visitors and a 10% cut adds ${+(elasticity * 10).toFixed(1)}% (never above slot capacity).`}
            </div>
          </div>
        </div>

        {error && <div className="alert alert-danger">{error}</div>}
        {!museum ? (
          <Empty title="Choose a place" />
        ) : loading && !data ? (
          <Loader />
        ) : data ? (
          <>
            {this.renderGrid(data)}
            <div className="card border-0 shadow-sm">
              <div className="card-body pb-0">
                <h2 className="h5 mb-1">Suggestions for {data.museum.name}</h2>
                <p className="small text-muted mb-3"><i className="bi bi-info-circle me-1" aria-hidden="true" />{data.assumption}</p>
              </div>
              {data.suggestions.length === 0 ? (
                <div className="card-body pt-0"><p className="text-muted mb-0">No slot was consistently busy or quiet in this period. Prices look right as they are.</p></div>
              ) : (
                <div className="list-group list-group-flush">{data.suggestions.map((s) => this.renderSuggestion(s, data))}</div>
              )}
            </div>
          </>
        ) : null}
      </div>
    );
  }
}

export default withAuth(PricingInsightsPage);
