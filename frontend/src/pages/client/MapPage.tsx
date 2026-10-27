import * as L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import * as React from 'react';
import { Link } from 'react-router-dom';
import { cachedGet } from '../../api/cache';
import { currentPosition, formatKm, geoErrorKind, GeoPlace, haversineKm } from '../../api/trips';
import type { PlaceType } from '../../api/types';
import { Loader } from '../../components/Common';
import { withI18n, WithI18nProps } from '../../i18n';
import { formatPrice, PLACE_TYPES } from '../../utils/format';
import { withRouter, WithRouterProps } from '../../utils/withRouter';

/** Marker colours: sky blue museums, orange shades for forts, palaces and monuments. */
const TYPE_STYLE: Record<PlaceType, { color: string; icon: string }> = {
  museum: { color: '#0284c7', icon: 'bi-bank' },
  fort: { color: '#ea580c', icon: 'bi-shield-shaded' },
  palace: { color: '#d97706', icon: 'bi-gem' },
  monument: { color: '#c2410c', icon: 'bi-building' },
};

const INDIA_CENTER: L.LatLngExpression = [22.5, 79];
const INDIA_ZOOM = 5;

const escapeHtml = (s: string): string =>
  s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string);

/** Places pinned at their city's centre would sit on top of each other: spread them a little (deterministic). */
function displayPosition(p: GeoPlace): [number, number] {
  if (!p.approximate) return [p.lat, p.lng];
  const angle = (p.id * 137.508 * Math.PI) / 180;
  const r = 0.012 + (p.id % 5) * 0.004; // roughly 1-3 km
  return [p.lat + r * Math.sin(angle), p.lng + r * Math.cos(angle)];
}

/** Pin in the place type's colour. Places pinned at their city's centre get a lighter, dashed pin. */
function markerIcon(type: PlaceType, approximate = false): L.DivIcon {
  const { color, icon } = TYPE_STYLE[type] ?? TYPE_STYLE.museum;
  const look = approximate ? 'opacity:.55;border:2px dashed #fff;box-shadow:0 1px 3px rgba(0,0,0,.25)' : 'border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.35)';
  return L.divIcon({
    className: approximate ? 'aa-map-marker aa-map-marker-approx' : 'aa-map-marker',
    html:
      `<span style="display:flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:50% 50% 50% 0;` +
      `transform:rotate(-45deg);background:${color};${look}">` +
      `<i class="bi ${icon}" style="transform:rotate(45deg);color:#fff;font-size:14px" aria-hidden="true"></i></span>`,
    iconSize: [30, 30],
    iconAnchor: [15, 30],
    popupAnchor: [0, -28],
  });
}

type MapPageProps = WithRouterProps & WithI18nProps;

interface MapPageState {
  places: GeoPlace[] | null;
  error: boolean;
  me: { lat: number; lng: number } | null;
  locating: boolean;
  geoError: string;
}

class MapPage extends React.Component<MapPageProps, MapPageState> {
  public state: MapPageState = { places: null, error: false, me: null, locating: false, geoError: '' };

  private mounted = false;
  private mapEl = React.createRef<HTMLDivElement>();
  private map: L.Map | null = null;
  private markers: L.LayerGroup | null = null;
  private meMarker: L.Layer | null = null;
  private markerBySlug = new Map<string, L.Marker>();
  private fitted = false;

  public componentDidMount(): void {
    this.mounted = true;
    if (this.mapEl.current) {
      this.map = L.map(this.mapEl.current, { center: INDIA_CENTER, zoom: INDIA_ZOOM, scrollWheelZoom: false });
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 18,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
      }).addTo(this.map);
      this.markers = L.layerGroup().addTo(this.map);
      this.map.on('focus', () => this.map?.scrollWheelZoom.enable()); // only zoom on wheel once the visitor engages
      this.map.on('blur', () => this.map?.scrollWheelZoom.disable());
      this.mapEl.current.addEventListener('click', this.onMapLinkClick, true);
    }
    cachedGet<GeoPlace[]>('/places/geo/', undefined, (places) => this.mounted && this.setState({ places })).catch(
      () => this.mounted && this.setState({ places: [], error: true }),
    );
  }

  public componentDidUpdate(prevProps: MapPageProps, prevState: MapPageState): void {
    const typeChanged = prevProps.router.searchParams.get('type') !== this.props.router.searchParams.get('type');
    const langChanged = prevProps.i18n.lang !== this.props.i18n.lang;
    if (prevState.places !== this.state.places || typeChanged || langChanged) this.drawMarkers();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    this.mapEl.current?.removeEventListener('click', this.onMapLinkClick, true);
    this.map?.remove();
    this.map = null;
  }

  /** Popup links are plain HTML: route them through React Router instead of reloading the page. */
  private onMapLinkClick = (e: MouseEvent): void => {
    const link = (e.target as HTMLElement).closest('a[data-route]');
    if (link && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
      e.preventDefault();
      this.props.router.navigate(link.getAttribute('data-route') as string);
    }
  };

  private get type(): string {
    const type = this.props.router.searchParams.get('type') ?? '';
    return PLACE_TYPES.some((p) => p.value === type) ? type : '';
  }

  private get visible(): GeoPlace[] {
    const type = this.type;
    return (this.state.places ?? []).filter((p) => !type || p.place_type === type);
  }

  private popupHtml(p: GeoPlace): string {
    const { t } = this.props.i18n;
    const price =
      p.starting_price === null
        ? t('common.card.ticketsSoon')
        : Number(p.starting_price) === 0
          ? t('common.free')
          : `${t('common.card.from')}${formatPrice(p.starting_price)}`;
    const route = `/museums/${encodeURIComponent(p.slug)}`;
    return (
      `<div style="width:200px">` +
      (p.image_url
        ? `<img src="${escapeHtml(p.image_url)}" alt="" loading="lazy" style="width:100%;height:110px;object-fit:cover;border-radius:6px;margin-bottom:6px" onerror="this.style.display='none'">`
        : '') +
      `<div class="fw-bold">${escapeHtml(p.name)}</div>` +
      `<div class="small text-muted">${escapeHtml(t(`common.type.${p.place_type}`))} · ${escapeHtml(p.city)}, ${escapeHtml(p.state)}</div>` +
      (p.approximate
        ? `<div class="small text-muted fst-italic"><i class="bi bi-geo me-1" aria-hidden="true"></i>${escapeHtml(t('trips.map.approx'))}</div>`
        : '') +
      `<div class="small fw-semibold my-1">${escapeHtml(price)}</div>` +
      `<a href="${route}" data-route="${route}" class="btn btn-sm btn-primary text-white w-100">${escapeHtml(t('trips.map.viewBook'))}</a>` +
      `</div>`
    );
  }

  private drawMarkers(): void {
    if (!this.map || !this.markers) return;
    this.markers.clearLayers();
    this.markerBySlug.clear();
    const { t } = this.props.i18n;
    const visible = this.visible;
    visible.forEach((p) => {
      const label = p.approximate ? `${p.name} (${t('trips.map.approxShort')})` : p.name;
      const marker = L.marker(displayPosition(p), { icon: markerIcon(p.place_type, p.approximate), title: label, alt: label, keyboard: true })
        .bindPopup(() => this.popupHtml(p));
      marker.addTo(this.markers as L.LayerGroup);
      this.markerBySlug.set(p.slug, marker);
    });
    if (!this.fitted && visible.length > 1 && !this.state.me) {
      this.fitted = true;
      this.map.fitBounds(L.latLngBounds(visible.map(displayPosition)), { padding: [30, 30], maxZoom: 7 });
    }
  }

  private setType = (type: string): void => {
    const next = new URLSearchParams(this.props.router.searchParams);
    if (type) next.set('type', type);
    else next.delete('type');
    this.props.router.setSearchParams(next, { replace: true });
  };

  private findMe = (): void => {
    const { t } = this.props.i18n;
    this.setState({ locating: true, geoError: '' });
    currentPosition()
      .then((me) => {
        if (!this.mounted) return;
        this.setState({ me, locating: false });
        if (this.map) {
          if (this.meMarker) this.meMarker.remove();
          this.meMarker = L.circleMarker([me.lat, me.lng], { radius: 9, color: '#fff', weight: 3, fillColor: '#2563eb', fillOpacity: 1 })
            .bindTooltip(t('trips.map.you'))
            .addTo(this.map);
          const nearest = this.nearest(me).slice(0, 3);
          const bounds = L.latLngBounds([[me.lat, me.lng], ...nearest.map((n) => displayPosition(n.place))]);
          this.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 12 });
        }
      })
      .catch((err) => this.mounted && this.setState({ locating: false, geoError: t(`trips.geo.${geoErrorKind(err)}`) }));
  };

  private nearest(me: { lat: number; lng: number }): { place: GeoPlace; km: number }[] {
    return this.visible
      .map((place) => ({ place, km: haversineKm(me.lat, me.lng, place.lat, place.lng) }))
      .sort((a, b) => a.km - b.km);
  }

  private focusPlace = (p: GeoPlace): void => {
    const marker = this.markerBySlug.get(p.slug);
    if (!this.map || !marker) return;
    this.map.setView(marker.getLatLng(), Math.max(this.map.getZoom(), 12));
    marker.openPopup();
    this.mapEl.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { places, error, me, locating, geoError } = this.state;
    const type = this.type;
    const visible = this.visible;
    const approxCount = visible.filter((p) => p.approximate).length;
    const nearest = me ? this.nearest(me).slice(0, 10) : [];
    const byState = new Map<string, GeoPlace[]>();
    visible.forEach((p) => byState.set(p.state, [...(byState.get(p.state) ?? []), p]));
    const states = Array.from(byState.keys()).sort((a, b) => a.localeCompare(b));

    return (
      <div className="container-fluid page py-4 px-lg-4">
        <div className="d-flex flex-wrap align-items-end gap-2 mb-3">
          <div className="me-auto">
            <h1 className="display-6 mb-1">{t('trips.map.title')}</h1>
            <p className="text-muted mb-0">{t('trips.map.subtitle')}</p>
          </div>
          <Link to="/museums" className="btn btn-outline-secondary btn-sm">
            <i className="bi bi-list-ul me-1" aria-hidden="true" />
            {t('trips.map.listView')}
          </Link>
        </div>

        <div className="d-flex flex-wrap align-items-center gap-2 mb-3" role="group" aria-label={t('trips.map.filter')}>
          <button type="button" className={`btn btn-sm rounded-pill btn-outline-primary ${!type ? 'active' : ''}`} aria-pressed={!type} onClick={() => this.setType('')}>
            {t('explore.all')}
          </button>
          {PLACE_TYPES.map((p) => (
            <button
              type="button"
              key={p.value}
              className={`btn btn-sm rounded-pill btn-outline-primary ${type === p.value ? 'active' : ''}`}
              aria-pressed={type === p.value}
              onClick={() => this.setType(p.value)}
            >
              <i className={`bi ${p.icon} me-1`} aria-hidden="true" />
              {t(`common.type.${p.value}s`)}
            </button>
          ))}
          <button type="button" className="btn btn-sm rounded-pill btn-accent ms-md-auto" onClick={this.findMe} disabled={locating || places === null}>
            {locating ? <span className="spinner-border spinner-border-sm me-1" aria-hidden="true" /> : <i className="bi bi-cursor me-1" aria-hidden="true" />}
            {t('trips.near.button')}
          </button>
        </div>

        {geoError && (
          <div className="alert alert-warning small py-2" role="alert">
            <i className="bi bi-exclamation-triangle me-2" aria-hidden="true" />
            {geoError}
          </div>
        )}
        {error && <div className="alert alert-danger small py-2">{t('trips.map.loadError')}</div>}

        <div className="row g-3">
          <div className={me ? 'col-lg-8 col-xl-9' : 'col-12'}>
            <div className="position-relative rounded-3 overflow-hidden shadow-sm border">
              <div
                ref={this.mapEl}
                style={{ height: '70vh', minHeight: 360, zIndex: 0 }}
                role="region"
                aria-label={t('trips.map.aria', { n: visible.length })}
              />
              {places === null && (
                <div className="position-absolute top-50 start-50 translate-middle" style={{ zIndex: 500 }}>
                  <Loader />
                </div>
              )}
              <div className="position-absolute bottom-0 start-0 m-2 bg-white rounded-2 shadow-sm px-2 py-1 small" style={{ zIndex: 500 }} aria-label={t('trips.map.legend')}>
                {PLACE_TYPES.map((p) => (
                  <div key={p.value} className="d-flex align-items-center">
                    <span className="d-inline-block rounded-circle me-2" style={{ width: 12, height: 12, background: TYPE_STYLE[p.value].color }} aria-hidden="true" />
                    {t(`common.type.${p.value}`)}
                  </div>
                ))}
              </div>
            </div>
            <p className="small text-muted mt-2 mb-0">
              {t('trips.map.count', { n: visible.length })}
              {approxCount > 0 && (
                <>
                  {' '}
                  <span className="d-inline-block rounded-circle align-middle me-1" style={{ width: 10, height: 10, border: '2px dashed #6c757d', opacity: 0.7 }} aria-hidden="true" />
                  {t('trips.map.approxCount', { n: approxCount })}
                </>
              )}
            </p>
          </div>

          {me && (
            <aside className="col-lg-4 col-xl-3" aria-live="polite">
              <div className="card border-0 shadow-sm h-100">
                <div className="card-body">
                  <h2 className="h6 mb-3">
                    <i className="bi bi-geo-alt-fill text-accent me-1" aria-hidden="true" />
                    {t('trips.map.nearest')}
                  </h2>
                  {nearest.length === 0 ? (
                    <p className="text-muted small mb-0">{t('trips.near.empty')}</p>
                  ) : (
                    <ol className="list-unstyled mb-0">
                      {nearest.map(({ place, km }, i) => (
                        <li key={place.id} className="d-flex align-items-start gap-2 py-2 border-bottom">
                          <span className="badge rounded-pill mt-1" style={{ background: TYPE_STYLE[place.place_type].color }}>{i + 1}</span>
                          <div className="flex-grow-1 min-w-0">
                            <button type="button" className="btn btn-link p-0 text-start fw-semibold text-decoration-none" onClick={() => this.focusPlace(place)}>
                              {place.name}
                            </button>
                            <div className="small text-muted">
                              {place.city} · {t(place.approximate ? 'trips.near.awayApprox' : 'trips.near.away', { distance: formatKm(km) })}
                            </div>
                          </div>
                          <Link to={`/museums/${place.slug}`} className="btn btn-sm btn-outline-primary" aria-label={`${t('trips.map.viewBook')}: ${place.name}`}>
                            <i className="bi bi-arrow-right" aria-hidden="true" />
                          </Link>
                        </li>
                      ))}
                    </ol>
                  )}
                </div>
              </div>
            </aside>
          )}
        </div>

        {/* Accessible alternative to the map: every pinned place as a plain list, by state. */}
        <section className="mt-4">
          <h2 className="h5">{t('trips.map.listTitle')}</h2>
          {states.map((s) => (
            <details key={s} className="border-bottom py-2">
              <summary className="fw-semibold">
                {s} <span className="text-muted fw-normal">({byState.get(s)?.length})</span>
              </summary>
              <ul className="list-unstyled row g-1 mt-2 mb-1">
                {(byState.get(s) ?? []).map((p) => (
                  <li key={p.id} className="col-sm-6 col-lg-4">
                    <i className={`bi ${TYPE_STYLE[p.place_type].icon} me-2`} style={{ color: TYPE_STYLE[p.place_type].color }} aria-hidden="true" />
                    <Link to={`/museums/${p.slug}`}>{p.name}</Link>
                    <span className="small text-muted"> · {p.city}</span>
                    {p.approximate && <span className="small text-muted fst-italic"> · {t('trips.map.approxShort')}</span>}
                  </li>
                ))}
              </ul>
            </details>
          ))}
        </section>
      </div>
    );
  }
}

export default withRouter(withI18n(MapPage));
