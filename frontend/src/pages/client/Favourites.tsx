import * as React from 'react';
import { Link } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import { FavouriteItem, FavouriteStore, TripSummary, tripsApi } from '../../api/trips';
import { Empty, Loader } from '../../components/Common';
import MuseumCard from '../../components/MuseumCard';
import { withI18n, WithI18nProps } from '../../i18n';

type FavouritesProps = WithI18nProps;

interface FavouritesState {
  items: FavouriteItem[] | null;
  error: string;
  trips: TripSummary[];
  /** Chosen trip per place slug, and a short confirmation after adding. */
  target: Record<string, string>;
  added: Record<string, string>;
  busy: string;
}

/** Saved places (login required: the lead wraps the route in RequireAuth). */
class Favourites extends React.Component<FavouritesProps, FavouritesState> {
  public state: FavouritesState = { items: null, error: '', trips: [], target: {}, added: {}, busy: '' };

  private mounted = false;
  private unsubscribe: (() => void) | null = null;

  public componentDidMount(): void {
    this.mounted = true;
    api
      .get<FavouriteItem[]>('/favourites/')
      .then((r) => this.mounted && this.setState({ items: r.data }))
      .catch((err) => this.mounted && this.setState({ items: [], error: errorMessage(err) }));
    tripsApi
      .list()
      .then((trips) => this.mounted && this.setState({ trips }))
      .catch(() => undefined);
    // A heart switched off here removes the card.
    this.unsubscribe = FavouriteStore.subscribe(() => {
      if (this.state.items) this.setState({ items: this.state.items.filter((i) => !FavouriteStore.loaded || FavouriteStore.has(i.museum.slug)) });
    });
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    this.unsubscribe?.();
  }

  private addToTrip = (slug: string): void => {
    const { t } = this.props.i18n;
    const tripId = this.state.target[slug] ?? (this.state.trips[0] ? String(this.state.trips[0].id) : '');
    if (!tripId) return;
    this.setState({ busy: slug });
    tripsApi
      .addStop(Number(tripId), slug)
      .then(() => {
        const title = this.state.trips.find((tr) => String(tr.id) === tripId)?.title ?? '';
        this.setState({ added: { ...this.state.added, [slug]: t('trips.fav.addedTo', { trip: title }) } });
      })
      .catch((err) => window.alert(errorMessage(err)))
      .finally(() => this.mounted && this.setState({ busy: '' }));
  };

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { items, error, trips, target, added, busy } = this.state;

    return (
      <div className="container page py-4 py-lg-5">
        <div className="d-flex flex-wrap align-items-end gap-2 mb-4">
          <div className="me-auto">
            <h1 className="display-6 mb-1">
              <i className="bi bi-heart-fill text-danger me-2" aria-hidden="true" />
              {t('trips.fav.title')}
            </h1>
            <p className="text-muted mb-0">{t('trips.fav.subtitle')}</p>
          </div>
          <Link to="/trips" className="btn btn-outline-primary btn-sm">
            <i className="bi bi-signpost-split me-1" aria-hidden="true" />
            {t('trips.planner.myTrips')}
          </Link>
        </div>

        {error && <div className="alert alert-danger">{error}</div>}
        {items === null ? (
          <Loader />
        ) : items.length === 0 ? (
          <Empty title={t('trips.fav.empty')}>
            <p>{t('trips.fav.emptyHint')}</p>
            <Link to="/museums" className="btn btn-primary">{t('trips.fav.explore')}</Link>
          </Empty>
        ) : (
          <div className="row g-4">
            {items.map(({ museum }) => (
              <div key={museum.id} className="col-sm-6 col-lg-4 col-xl-3 d-flex flex-column">
                <div className="flex-grow-1">
                  <MuseumCard museum={museum} />
                </div>
                <div className="mt-2">
                  {trips.length === 0 ? (
                    <Link to="/trips" className="btn btn-sm btn-outline-secondary w-100">
                      <i className="bi bi-calendar-plus me-1" aria-hidden="true" />
                      {t('trips.fav.planTrip')}
                    </Link>
                  ) : (
                    <div className="input-group input-group-sm">
                      <select
                        className="form-select"
                        aria-label={t('trips.fav.chooseTrip', { name: museum.name })}
                        value={target[museum.slug] ?? String(trips[0].id)}
                        onChange={(e) => this.setState({ target: { ...target, [museum.slug]: e.target.value } })}
                      >
                        {trips.map((tr) => (
                          <option key={tr.id} value={tr.id}>{tr.title}</option>
                        ))}
                      </select>
                      <button type="button" className="btn btn-outline-primary" onClick={() => this.addToTrip(museum.slug)} disabled={busy === museum.slug}>
                        <i className="bi bi-plus-lg me-1" aria-hidden="true" />
                        {t('trips.fav.addToTrip')}
                      </button>
                    </div>
                  )}
                  {added[museum.slug] && (
                    <div className="small text-success mt-1" role="status">
                      <i className="bi bi-check-lg me-1" aria-hidden="true" />
                      {added[museum.slug]}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }
}

export default withI18n(Favourites);
