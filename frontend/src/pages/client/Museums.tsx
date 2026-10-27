import * as React from 'react';
import { Link } from 'react-router-dom';
import { cachedGet } from '../../api/cache';
import { currentPosition, formatKm, geoErrorKind, GeoPlace, nearby } from '../../api/trips';
import type { Category, City, MuseumSummary, Paginated, State } from '../../api/types';
import { Empty, Loader, Pagination } from '../../components/Common';
import MuseumCard from '../../components/MuseumCard';
import { withI18n, WithI18nProps } from '../../i18n';
import { PLACE_TYPES } from '../../utils/format';
import { withRouter, WithRouterProps } from '../../utils/withRouter';

/** Counts per option, each computed with the *other* active filters applied (see /museums/facets/). */
interface Facets {
  total: number;
  type: Record<string, number>;
  state: Record<string, number>;
  city: Record<string, number>;
  category: Record<string, number>;
}

const FILTER_KEYS = ['search', 'type', 'state', 'city', 'category'] as const;
const sum = (o: Record<string, number> | undefined): number => Object.values(o ?? {}).reduce((a, b) => a + b, 0);

type MuseumsProps = WithRouterProps & WithI18nProps;

interface MuseumsState {
  data: Paginated<MuseumSummary> | null;
  facets: Facets | null;
  states: State[];
  cities: City[];
  categories: Category[];
  search: string;
  /** "Near me": the visitor's position and the places sorted by distance (null when inactive). */
  near: { lat: number; lng: number } | null;
  nearResults: GeoPlace[] | null;
  nearWidened: boolean;
  nearBusy: boolean;
  nearError: string;
}

const NEAR_RADIUS_KM = 100;

/** The nearby endpoint's compact rows, shaped for MuseumCard. */
const geoToSummary = (p: GeoPlace): MuseumSummary => ({
  id: p.id,
  name: p.name,
  slug: p.slug,
  place_type: p.place_type,
  tagline: '',
  image_url: p.image_url,
  city_name: p.city,
  state_name: p.state,
  category_name: null,
  opening_time: '',
  closing_time: '',
  closed_weekday: null,
  is_featured: false,
  is_active: true,
  starting_price: p.starting_price,
  avg_rating: null,
  review_count: 0,
});

class Museums extends React.Component<MuseumsProps, MuseumsState> {
  public state: MuseumsState = {
    data: null,
    facets: null,
    states: [],
    cities: [],
    categories: [],
    search: this.props.router.searchParams.get('search') ?? '',
    near: null,
    nearResults: null,
    nearWidened: false,
    nearBusy: false,
    nearError: '',
  };

  private nearRequest = 0;

  private mounted = false;
  private citiesRequest = 0;
  private facetsRequest = 0;
  private listRequest = 0;
  private searchTimer: ReturnType<typeof setTimeout> | null = null;

  public componentDidMount(): void {
    this.mounted = true;
    cachedGet<State[]>('/states/', undefined, (states) => this.mounted && this.setState({ states })).catch(() => undefined);
    cachedGet<Category[]>('/categories/', undefined, (categories) => this.mounted && this.setState({ categories })).catch(() => undefined);
    this.loadCities();
    this.loadFacets();
    this.loadList();
    this.scheduleSearch();
  }

  public componentDidUpdate(prevProps: MuseumsProps, prevState: MuseumsState): void {
    const prevParams = prevProps.router.searchParams;
    const params = this.props.router.searchParams;
    if ((prevParams.get('state') ?? '') !== (params.get('state') ?? '')) this.loadCities();
    if (Museums.filterKey(prevParams) !== Museums.filterKey(params)) this.loadFacets();
    if (prevProps.router.location.search !== this.props.router.location.search) this.loadList();
    if (prevState.search !== this.state.search) this.scheduleSearch();
    if (this.state.near && (prevParams.get('type') ?? '') !== (params.get('type') ?? '')) this.loadNearby(this.state.near);
  }

  private findNearMe = (): void => {
    const { t } = this.props.i18n;
    this.setState({ nearBusy: true, nearError: '' });
    currentPosition()
      .then((pos) => {
        if (!this.mounted) return;
        this.setState({ near: pos });
        this.loadNearby(pos);
      })
      .catch((err) => this.mounted && this.setState({ nearBusy: false, nearError: t(`trips.geo.${geoErrorKind(err)}`) }));
  };

  private loadNearby(pos: { lat: number; lng: number }): void {
    const id = ++this.nearRequest;
    const type = this.params.get('type') ?? undefined;
    this.setState({ nearBusy: true, nearResults: null });
    nearby(pos.lat, pos.lng, { radius_km: NEAR_RADIUS_KM, type, limit: 48 })
      // Nothing close by: show the nearest ones anyway, further away.
      .then((r) => (r.count > 0 ? { r, widened: false } : nearby(pos.lat, pos.lng, { radius_km: 5000, type, limit: 12 }).then((w) => ({ r: w, widened: true }))))
      .then(({ r, widened }) => {
        if (this.mounted && id === this.nearRequest) this.setState({ nearResults: r.results, nearWidened: widened, nearBusy: false });
      })
      .catch(() => {
        if (this.mounted && id === this.nearRequest) this.setState({ nearBusy: false, nearResults: [], nearError: this.props.i18n.t('trips.near.error') });
      });
  }

  private clearNear = (): void => {
    this.nearRequest++;
    this.setState({ near: null, nearResults: null, nearBusy: false, nearError: '', nearWidened: false });
  };

  public componentWillUnmount(): void {
    this.mounted = false;
    if (this.searchTimer !== null) clearTimeout(this.searchTimer);
  }

  private get params(): URLSearchParams {
    return this.props.router.searchParams;
  }

  // Filters only (no page), so changing page doesn't refetch counts.
  private static filterQuery(params: URLSearchParams): Record<string, string> {
    const q: Record<string, string> = {};
    FILTER_KEYS.forEach((k) => {
      const v = params.get(k);
      if (v) q[k] = v;
    });
    return q;
  }

  private static filterKey(params: URLSearchParams): string {
    return JSON.stringify(Museums.filterQuery(params));
  }

  private loadCities(): void {
    const id = ++this.citiesRequest;
    const state = this.params.get('state') ?? '';
    this.setState({ cities: [] });
    if (state)
      cachedGet<City[]>('/cities/', { state }, (cities) => {
        if (this.mounted && id === this.citiesRequest) this.setState({ cities });
      }).catch(() => undefined);
  }

  private loadFacets(): void {
    const id = ++this.facetsRequest;
    cachedGet<Facets>('/museums/facets/', Museums.filterQuery(this.params), (f) => {
      if (this.mounted && id === this.facetsRequest) this.setState({ facets: f });
    }).catch(() => undefined);
  }

  private loadList(): void {
    this.setState({ data: null });
    const query: Record<string, string> = {};
    this.params.forEach((v, k) => v && (query[k] = v));
    const id = ++this.listRequest;
    const alive = (): boolean => this.mounted && id === this.listRequest;
    cachedGet<Paginated<MuseumSummary>>('/museums/', query, (d) => alive() && this.setState({ data: d })).catch(() =>
      alive() && this.setState({ data: { count: 0, next: null, previous: null, results: [] } }),
    );
  }

  // Debounce free-text search into the URL
  private scheduleSearch(): void {
    if (this.searchTimer !== null) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => {
      this.searchTimer = null;
      const { search } = this.state;
      if ((this.params.get('search') ?? '') !== search) this.update({ search });
    }, 350);
  }

  private update = (changes: Record<string, string>): void => {
    const next = new URLSearchParams(this.params);
    Object.entries(changes).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    if (!('page' in changes)) next.delete('page');
    this.props.router.setSearchParams(next);
  };

  public render(): React.ReactNode {
    const params = this.params;
    const { data, facets, states, cities, categories, search, near, nearResults, nearWidened, nearBusy, nearError } = this.state;
    const { setSearchParams: setParams } = this.props.router;
    const { t } = this.props.i18n;

    const state = params.get('state') ?? '';
    const city = params.get('city') ?? '';
    const category = params.get('category') ?? '';
    const type = params.get('type') ?? '';
    const page = Number(params.get('page') ?? 1);
    const update = this.update;

    // "(n)" for an option; options with nothing to show are disabled unless already selected.
    const count = (group: keyof Omit<Facets, 'total'>, id: string | number): number => facets?.[group][String(id)] ?? 0;
    const label = (n: number): string => (facets ? ` (${n})` : '');

    const stateName = states.find((s) => String(s.id) === state)?.name;
    const cityName = cities.find((c) => String(c.id) === city)?.name;
    const categoryName = categories.find((c) => String(c.id) === category)?.name;
    const typePlural = PLACE_TYPES.some((p) => p.value === type) ? t(`common.type.${type}s`) : undefined;

    // When nothing matches, offer to relax one filter at a time, with how many results each would give.
    const suggestions: { text: string; n: number; changes: Record<string, string> }[] = [];
    if (facets && data?.count === 0) {
      if (category) suggestions.push({ text: stateName ? t('explore.suggest.allCollectionsIn', { place: cityName ?? stateName }) : t('explore.suggest.allCollections'), n: sum(facets.category), changes: { category: '' } });
      if (type) suggestions.push({ text: stateName ? t('explore.suggest.allTypesIn', { place: cityName ?? stateName }) : t('explore.suggest.allTypes'), n: sum(facets.type), changes: { type: '' } });
      if (city) suggestions.push({ text: t('explore.suggest.allCitiesIn', { state: stateName ?? '' }), n: sum(facets.city), changes: { city: '' } });
      if (state) suggestions.push({ text: t('explore.suggest.inAllStates', { what: categoryName ?? typePlural ?? t('explore.suggest.matching') }), n: sum(facets.state), changes: { state: '', city: '' } });
    }

    return (
      <div className="container page py-4 py-lg-5">
        <h1 className="display-6">{t('explore.title')}</h1>
        <p className="text-muted mb-4">{t('explore.subtitle')}</p>

        <div className="d-flex flex-wrap gap-2 mb-3" role="group" aria-label={t('explore.typeLabel')}>
          <button type="button" className={`btn btn-sm rounded-pill btn-outline-primary ${!type ? 'active' : ''}`} onClick={() => update({ type: '' })}>
            {t('explore.all')}{label(sum(facets?.type))}
          </button>
          {PLACE_TYPES.map((p) => {
            const n = count('type', p.value);
            return (
              <button
                type="button"
                key={p.value}
                className={`btn btn-sm rounded-pill btn-outline-primary ${type === p.value ? 'active' : ''}`}
                onClick={() => update({ type: p.value })}
                disabled={!!facets && n === 0 && type !== p.value}
              >
                <i className={`bi ${p.icon} me-1`} aria-hidden="true" />
                {t(`common.type.${p.value}s`)}{label(n)}
              </button>
            );
          })}
          <span className="ms-auto d-flex flex-wrap gap-2">
            <button type="button" className={`btn btn-sm rounded-pill btn-outline-accent ${near ? 'active' : ''}`} onClick={this.findNearMe} disabled={nearBusy} aria-pressed={!!near}>
              {nearBusy ? <span className="spinner-border spinner-border-sm me-1" aria-hidden="true" /> : <i className="bi bi-cursor me-1" aria-hidden="true" />}
              {t('trips.near.button')}
            </button>
            <Link to={type ? `/map?type=${type}` : '/map'} className="btn btn-sm rounded-pill btn-outline-secondary">
              <i className="bi bi-map me-1" aria-hidden="true" />
              {t('trips.near.mapView')}
            </Link>
          </span>
        </div>
        {nearError && (
          <div className="alert alert-warning small py-2 d-flex align-items-center" role="alert">
            <i className="bi bi-exclamation-triangle me-2" aria-hidden="true" />
            <span className="me-auto">{nearError}</span>
            <button type="button" className="btn-close btn-sm" aria-label={t('trips.common.close')} onClick={() => this.setState({ nearError: '' })} />
          </div>
        )}

        <div className="card border-0 shadow-sm mb-4">
          <div className="card-body">
            <div className="row g-2">
              <div className="col-lg-5">
                <div className="input-group">
                  <span className="input-group-text bg-white">
                    <i className="bi bi-search" aria-hidden="true" />
                  </span>
                  <input className="form-control" placeholder={t('explore.search.placeholder')} value={search} onChange={(e) => this.setState({ search: e.target.value })} aria-label={t('explore.search.label')} />
                </div>
              </div>
              <div className="col-md-4 col-lg">
                <select className="form-select" value={state} onChange={(e) => update({ state: e.target.value, city: '' })} aria-label={t('explore.state.label')}>
                  <option value="">{t('explore.state.all')}{label(sum(facets?.state))}</option>
                  {states.map((s) => {
                    const n = count('state', s.id);
                    return (
                      <option key={s.id} value={s.id} disabled={!!facets && n === 0 && state !== String(s.id)}>
                        {s.name}{label(n)}
                      </option>
                    );
                  })}
                </select>
              </div>
              <div className="col-md-4 col-lg">
                <select className="form-select" value={city} onChange={(e) => update({ city: e.target.value })} disabled={!state} aria-label={t('explore.city.label')}>
                  <option value="">{state ? `${t('explore.city.all')}${label(sum(facets?.city))}` : t('explore.city.pickState')}</option>
                  {cities.map((c) => {
                    const n = count('city', c.id);
                    return (
                      <option key={c.id} value={c.id} disabled={!!facets && n === 0 && city !== String(c.id)}>
                        {c.name}{label(n)}
                      </option>
                    );
                  })}
                </select>
              </div>
              <div className="col-md-4 col-lg">
                <select className="form-select" value={category} onChange={(e) => update({ category: e.target.value })} aria-label={t('explore.collection.label')}>
                  <option value="">{t('explore.collection.all')}{label(sum(facets?.category))}</option>
                  {categories.map((c) => {
                    const n = count('category', c.id);
                    return (
                      <option key={c.id} value={c.id} disabled={!!facets && n === 0 && category !== String(c.id)}>
                        {c.name}{label(n)}
                      </option>
                    );
                  })}
                </select>
              </div>
            </div>
          </div>
        </div>

        {near ? (
          <section aria-live="polite">
            <div className="d-flex flex-wrap align-items-center gap-2 mb-3">
              <h2 className="h5 mb-0 me-auto">
                <i className="bi bi-geo-alt-fill text-accent me-1" aria-hidden="true" />
                {nearResults && nearWidened ? t('trips.near.widened', { km: NEAR_RADIUS_KM }) : t('trips.near.title', { km: NEAR_RADIUS_KM })}
              </h2>
              <button type="button" className="btn btn-sm btn-light" onClick={this.clearNear}>
                <i className="bi bi-x-lg me-1" aria-hidden="true" />
                {t('trips.near.clear')}
              </button>
            </div>
            {nearResults === null ? (
              <Loader />
            ) : nearResults.length === 0 ? (
              <Empty title={t('trips.near.empty')} />
            ) : (
              <div className="row g-4">
                {nearResults.map((p) => (
                  <div key={p.id} className="col-sm-6 col-lg-4 col-xl-3 position-relative">
                    <MuseumCard museum={geoToSummary(p)} />
                    <span className="badge bg-dark position-absolute top-0 start-0 mt-2 ms-4 shadow-sm" style={{ zIndex: 3 }}>
                      <i className="bi bi-geo-alt me-1" aria-hidden="true" />
                      {t(p.approximate ? 'trips.near.awayApprox' : 'trips.near.away', { distance: formatKm(p.distance_km ?? 0) })}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>
        ) : data === null ? (
          <Loader />
        ) : data.count === 0 ? (
          <Empty title={t('explore.empty.title')}>
            <p className="text-muted">
              {[typePlural, categoryName && `"${categoryName}"`, cityName ?? stateName, params.get('search') && `"${params.get('search')}"`]
                .filter(Boolean)
                .join(' · ')}
            </p>
            <div className="d-flex flex-wrap justify-content-center gap-2">
              {suggestions
                .filter((s) => s.n > 0)
                .map((s) => (
                  <button type="button" key={s.text} className="btn btn-outline-primary btn-sm" onClick={() => update(s.changes)}>
                    {s.text} ({s.n})
                  </button>
                ))}
              <button type="button" className="btn btn-light btn-sm" onClick={() => { this.setState({ search: '' }); setParams({}); }}>
                {t('explore.clearAll')}
              </button>
            </div>
          </Empty>
        ) : (
          <>
            <p className="text-muted small mb-3">
              {t(data.count > 1 ? 'explore.found.other' : 'explore.found.one', { n: data.count })}
            </p>
            <div className="row g-4">
              {data.results.map((m) => (
                <div key={m.id} className="col-sm-6 col-lg-4 col-xl-3">
                  <MuseumCard museum={m} />
                </div>
              ))}
            </div>
            <Pagination page={page} count={data.count} onChange={(p) => update({ page: String(p) })} />
          </>
        )}
      </div>
    );
  }
}

export default withRouter(withI18n(Museums));
