import * as React from 'react';
import { Link } from 'react-router-dom';
import { cachedGet } from '../../api/cache';
import type { Category, MuseumSummary, Paginated, State } from '../../api/types';
import { Loader } from '../../components/Common';
import MuseumCard from '../../components/MuseumCard';
import { withI18n, WithI18nProps } from '../../i18n';
import { PLACE_TYPES, sizedImage } from '../../utils/format';
import { withRouter, WithRouterProps } from '../../utils/withRouter';

type HomeProps = WithRouterProps & WithI18nProps;

interface HomeState {
  featured: MuseumSummary[] | null;
  heritage: MuseumSummary[] | null;
  typeCounts: Record<string, number>;
  states: State[];
  categories: Category[];
  total: number;
  search: string;
  state: string;
}

class Home extends React.Component<HomeProps, HomeState> {
  public state: HomeState = {
    featured: null,
    heritage: null,
    typeCounts: {},
    states: [],
    categories: [],
    total: 0,
    search: '',
    state: '',
  };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    // Each call paints from IndexedDB first, then refreshes from the API.
    const ignore = (): undefined => undefined;
    const set = <K extends keyof HomeState>(patch: Pick<HomeState, K>): void => {
      if (this.mounted) this.setState(patch);
    };
    cachedGet<Paginated<MuseumSummary>>('/museums/', { featured: true, type: 'museum' }, (d) => set({ featured: d.results.slice(0, 6) })).catch(ignore);
    cachedGet<Paginated<MuseumSummary>>('/museums/?featured=true&type=fort&type=palace&type=monument', undefined, (d) =>
      set({ heritage: d.results.slice(0, 6) }),
    ).catch(ignore);
    PLACE_TYPES.forEach((p) =>
      cachedGet<Paginated<MuseumSummary>>('/museums/', { type: p.value }, (d) => {
        if (this.mounted) this.setState((s) => ({ typeCounts: { ...s.typeCounts, [p.value]: d.count } }));
      }).catch(ignore),
    );
    cachedGet<Paginated<MuseumSummary>>('/museums/', undefined, (d) => set({ total: d.count })).catch(ignore);
    cachedGet<State[]>('/states/', undefined, (states) => set({ states })).catch(ignore);
    cachedGet<Category[]>('/categories/', undefined, (categories) => set({ categories })).catch(ignore);
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private onSearch = (e: React.FormEvent): void => {
    e.preventDefault();
    const { search, state } = this.state;
    const params = new URLSearchParams();
    if (search) params.set('search', search);
    if (state) params.set('state', state);
    this.props.router.navigate(`/museums?${params}`);
  };

  public render(): React.ReactNode {
    const { featured, heritage, typeCounts, states, categories, total, search, state } = this.state;
    const { t } = this.props.i18n;
    const statesWithMuseums = states.filter((s) => s.museum_count > 0);
    const heroPlace = heritage?.find((m) => m.image_url);
    const heroStyle: React.CSSProperties | undefined = heroPlace
      ? { backgroundImage: `url("${sizedImage(heroPlace.image_url, 1280)}")` }
      : undefined;

    return (
      <>
        <section className="hero" style={heroStyle}>
          <div className="container">
            <div className="hero-kicker mb-3">{t('home.hero.kicker')}</div>
            <h1 className="display-4 mb-3">{t('home.hero.title')}</h1>
            <p className="lead mb-4">{t('home.hero.lead')}</p>
            <form className="hero-search row g-2 mx-0" onSubmit={this.onSearch}>
              <div className="col-md">
                <div className="input-group">
                  <span className="input-group-text bg-white border-end-0">
                    <i className="bi bi-search" aria-hidden="true" />
                  </span>
                  <input
                    className="form-control border-start-0"
                    placeholder={t('home.search.placeholder')}
                    value={search}
                    onChange={(e) => this.setState({ search: e.target.value })}
                    aria-label={t('home.search.label')}
                  />
                </div>
              </div>
              <div className="col-md-4">
                <select className="form-select" value={state} onChange={(e) => this.setState({ state: e.target.value })} aria-label={t('home.search.state')}>
                  <option value="">{t('home.search.allStates')}</option>
                  {states.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="col-md-auto d-grid">
                <button className="btn btn-accent" type="submit">
                  {t('home.search.submit')}
                </button>
              </div>
            </form>
            <div className="d-flex flex-wrap gap-5 mt-5">
              <div className="hero-stat"><strong>{total || '—'}</strong><span>{t('home.stats.places')}</span></div>
              <div className="hero-stat"><strong>{statesWithMuseums.length || '—'}</strong><span>{t('home.stats.states')}</span></div>
              <div className="hero-stat"><strong>QR</strong><span>{t('home.stats.qr')}</span></div>
            </div>
          </div>
          {heroPlace && <div className="hero-credit">{t('home.hero.pictured', { name: heroPlace.name })}</div>}
        </section>

        <div className="container page py-4 py-lg-5">
          <section className="row g-4" aria-label={t('home.types.label')}>
            {PLACE_TYPES.map((p) => (
              <div key={p.value} className="col-6 col-md-3">
                <Link to={`/museums?type=${p.value}`} className={`card border-0 shadow-sm type-tile type-${p.value} h-100`}>
                  <div className="card-body">
                    <i className={`bi ${p.icon} type-icon d-block mb-2`} aria-hidden="true" />
                    <strong className="d-block fs-5">{t(`common.type.${p.value}s`)}</strong>
                    <span className="text-muted small">{t(typeCounts[p.value] === 1 ? 'home.places.one' : 'home.places.other', { n: typeCounts[p.value] ?? '…' })}</span>
                  </div>
                </Link>
              </div>
            ))}
          </section>

          <section className="mt-5">
            <div className="d-flex justify-content-between align-items-end mb-3">
              <h2 className="mb-0">{t('home.heritage.title')}</h2>
              <Link to="/museums?type=fort" className="btn btn-link">{t('home.viewAll')}</Link>
            </div>
            {heritage === null ? (
              <Loader />
            ) : (
              <div className="row g-4">
                {heritage.map((m) => (
                  <div key={m.id} className="col-sm-6 col-lg-4">
                    <MuseumCard museum={m} />
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="mt-5">
            <div className="d-flex justify-content-between align-items-end mb-3">
              <h2 className="mb-0">{t('home.featured.title')}</h2>
              <Link to="/museums?type=museum" className="btn btn-link">{t('home.viewAll')}</Link>
            </div>
            {featured === null ? (
              <Loader />
            ) : (
              <div className="row g-4">
                {featured.map((m) => (
                  <div key={m.id} className="col-sm-6 col-lg-4">
                    <MuseumCard museum={m} />
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="mt-5">
            <h2 className="mb-3">{t('home.collections.title')}</h2>
            <div className="d-flex flex-wrap gap-2">
              {categories.map((c) => (
                <Link key={c.id} to={`/museums?category=${c.id}`} className="btn btn-sm rounded-pill btn-outline-primary">
                  {c.name}
                </Link>
              ))}
            </div>
          </section>

          <section className="mt-5">
            <h2 className="mb-3">{t('home.states.title')}</h2>
            <div className="row g-3">
              {statesWithMuseums.map((s) => (
                <div key={s.id} className="col-6 col-md-4 col-lg-3">
                  <Link to={`/museums?state=${s.id}`} className="card border-0 shadow-sm h-100 text-decoration-none text-body">
                    <div className="card-body py-3">
                      <strong className="d-block">{s.name}</strong>
                      <div className="text-muted small">
                        {t(s.museum_count > 1 ? 'home.places.other' : 'home.places.one', { n: s.museum_count })}
                      </div>
                    </div>
                  </Link>
                </div>
              ))}
            </div>
          </section>

          <section className="mt-5">
            <h2 className="mb-3">{t('home.how.title')}</h2>
            <div className="row g-4">
              {['1', '2', '3'].map((n) => (
                <div key={n} className="col-md-4">
                  <div className="card border-0 shadow-sm h-100">
                    <div className="card-body p-4">
                      <span className="badge rounded-pill bg-accent">{t('home.how.step', { n })}</span>
                      <h3 className="h4 mt-3">{t(`home.how.${n}.title`)}</h3>
                      <p className="text-muted mb-0">{t(`home.how.${n}.text`)}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      </>
    );
  }
}

export default withRouter(withI18n(Home));
