import * as React from 'react';
import { Link } from 'react-router-dom';
import { cachedGet } from '../../api/cache';
import { EVENT_KINDS, KIND_ICONS } from '../../api/events';
import type { EventKind, EventSummary } from '../../api/events';
import type { State } from '../../api/types';
import { Empty, Loader } from '../../components/Common';
import { withI18n, WithI18nProps } from '../../i18n';
import { formatDate, formatINR, museumGradient, sizedImage } from '../../utils/format';
import { withRouter, WithRouterProps } from '../../utils/withRouter';
import FxHint from '../../components/FxHint';
import { loadSiteSettings } from '../../api/siteSettings';
import type { SiteSettings } from '../../api/siteSettings';
import { placeLocation } from '../../utils/format';

/** /events: light & sound shows, night viewings, walks... filterable by kind and state (?kind=&state=). */

type EventsProps = WithRouterProps & WithI18nProps;

interface EventsState {
  events: EventSummary[] | null;
  states: State[];
  error: string;
  site: SiteSettings | null;
}

class Events extends React.Component<EventsProps, EventsState> {
  public state: EventsState = { events: null, states: [], error: '', site: null };

  private mounted = false;
  private request = 0;

  public componentDidMount(): void {
    this.mounted = true;
    cachedGet<State[]>('/states/', undefined, (states) => this.mounted && this.setState({ states })).catch(() => undefined);
    loadSiteSettings((site) => this.mounted && this.setState({ site })).catch(() => undefined);
    this.load();
  }

  public componentDidUpdate(prevProps: EventsProps): void {
    if (prevProps.router.location.search !== this.props.router.location.search) this.load();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private get kind(): string {
    return this.props.router.searchParams.get('kind') ?? '';
  }

  private get stateId(): string {
    return this.props.router.searchParams.get('state') ?? '';
  }

  private load(): void {
    const id = ++this.request;
    this.setState({ events: null, error: '' });
    cachedGet<EventSummary[]>('/events/', { kind: this.kind || undefined, state: this.stateId || undefined }, (events) => {
      if (this.mounted && id === this.request) this.setState({ events });
    }).catch(() => {
      if (this.mounted && id === this.request) this.setState({ events: [], error: this.props.i18n.t('events.loadError') });
    });
  }

  private setFilter(key: 'kind' | 'state', value: string): void {
    const params = new URLSearchParams(this.props.router.searchParams);
    if (value) params.set(key, value);
    else params.delete(key);
    this.props.router.setSearchParams(params, { replace: true });
  }

  private renderCard(e: EventSummary): React.ReactNode {
    const { t } = this.props.i18n;
    const image = e.image_url || e.museum_image;
    return (
      <div key={e.id} className="col-sm-6 col-lg-4">
        <div className="card h-100 border-0 shadow-sm overflow-hidden" data-testid="event-card">
          <div
            className="position-relative"
            style={{ height: 170, background: image ? `center / cover no-repeat url("${sizedImage(image, 500)}")` : museumGradient(e.slug) }}
            role="img"
            aria-label={e.title}
          >
            <span className="badge bg-accent position-absolute top-0 start-0 m-2">
              <i className={`bi ${KIND_ICONS[e.kind]} me-1`} aria-hidden="true" />
              {t(`events.kind.${e.kind}`)}
            </span>
            {e.featured && (
              <span className="badge bg-light text-dark position-absolute top-0 end-0 m-2">
                <i className="bi bi-star-fill text-warning me-1" aria-hidden="true" />
                {t('events.featured')}
              </span>
            )}
          </div>
          <div className="card-body d-flex flex-column">
            <h2 className="h5 card-title mb-1">{e.title}</h2>
            <div className="small text-muted mb-2">
              <i className="bi bi-geo-alt text-primary me-1" aria-hidden="true" />
              {e.museum_name} · {placeLocation(e.city_name, e.state_name)}
            </div>
            <ul className="list-unstyled small mb-3">
              {e.next_date && (
                <li>
                  <i className="bi bi-calendar-event text-primary me-1" aria-hidden="true" />
                  {t('events.next', { date: formatDate(e.next_date, { weekday: 'short', day: 'numeric', month: 'short' }) })}
                </li>
              )}
              <li>
                <i className="bi bi-stopwatch text-primary me-1" aria-hidden="true" />
                {t('events.minutes', { n: e.duration_minutes })}
                {e.language && <> · {e.language}</>}
              </li>
            </ul>
            <div className="mt-auto d-flex justify-content-between align-items-end">
              <div>
                {e.from_price !== null && (
                  <>
                    <div className="small text-muted">{t('events.from')}</div>
                    <div className="fs-4 fw-bold">{Number(e.from_price) === 0 ? t('common.free') : formatINR(e.from_price)}</div>
                    {Number(e.from_price) > 0 && <FxHint amount={e.from_price} className="d-block" />}
                  </>
                )}
              </div>
              <Link to={`/events/${e.slug}`} className="btn btn-accent" aria-label={t('events.viewAria', { name: e.title })}>
                {t('events.view')}
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { events, states, error } = this.state;
    const kind = this.kind;
    return (
      <div className="container page py-4 py-lg-5">
        <h1 className="mb-1">{t('events.title')}</h1>
        <p className="lead text-secondary">{t('events.lead')}</p>
        {this.state.site && !this.state.site.events_enabled && (
          <div className="alert alert-warning"><i className="bi bi-pause-circle me-2" aria-hidden="true" />{this.state.site.paused_message || t('common.paused.events')}</div>
        )}

        <div className="d-flex flex-wrap gap-2 align-items-center mb-4">
          <div className="d-flex flex-wrap gap-2" role="group" aria-label={t('events.filter.kind')}>
            <button type="button" className={`btn btn-sm ${!kind ? 'btn-primary' : 'btn-outline-primary'}`} aria-pressed={!kind} onClick={() => this.setFilter('kind', '')}>
              {t('events.filter.all')}
            </button>
            {EVENT_KINDS.map((k: EventKind) => (
              <button key={k} type="button" className={`btn btn-sm ${kind === k ? 'btn-primary' : 'btn-outline-primary'}`} aria-pressed={kind === k} onClick={() => this.setFilter('kind', k)}>
                <i className={`bi ${KIND_ICONS[k]} me-1`} aria-hidden="true" />
                {t(`events.kind.${k}`)}
              </button>
            ))}
          </div>
          <div className="ms-md-auto">
            <label htmlFor="ev-state" className="visually-hidden">{t('events.filter.state')}</label>
            <select id="ev-state" className="form-select form-select-sm" value={this.stateId} onChange={(e) => this.setFilter('state', e.target.value)}>
              <option value="">{t('events.filter.allStates')}</option>
              {states.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>
        </div>

        {error && <div className="alert alert-danger">{error}</div>}
        {events === null ? (
          <Loader />
        ) : events.length === 0 ? (
          <Empty title={t('events.empty')}>
            <Link to="/museums" className="btn btn-outline-primary">{t('events.explorePlaces')}</Link>
          </Empty>
        ) : (
          <div className="row g-4">{events.map((e) => this.renderCard(e))}</div>
        )}
      </div>
    );
  }
}

export default withRouter(withI18n(Events));
