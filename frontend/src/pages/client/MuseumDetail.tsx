import * as React from 'react';
import { Link } from 'react-router-dom';
import { track } from '../../api/analytics';
import { cachedGet } from '../../api/cache';
import { api, errorMessage } from '../../api/client';
import { KIND_ICONS } from '../../api/events';
import type { EventSummary } from '../../api/events';
import { GROUP_TYPES } from '../../api/types';
import type { Booking, GroupType, Museum } from '../../api/types';
import { CROWD_DOT, FACILITY_FLAGS, FACILITY_TEXTS } from '../../api/placeinfo';
import type { AvailabilityInfo, MuseumWithInfo, PublicClosure, SlotAvailabilityInfo } from '../../api/placeinfo';
import AuthModal from '../../components/AuthModal';
import FxHint from '../../components/FxHint';
import { Empty, Loader } from '../../components/Common';
import { Description } from '../../components/MuseumStory';
import PhotoCarousel from '../../components/PhotoCarousel';
import Reviews, { Stars } from '../../components/Reviews';
import WaitlistButton from '../../components/WaitlistButton';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { withI18n, WithI18nProps } from '../../i18n';
import { djangoWeekday, formatDate, formatINR, formatPrice, formatTime, isoDate } from '../../utils/format';
import { withRouter, WithRouterProps } from '../../utils/withRouter';
import { fetchPlaceAddOns } from '../../api/addons';
import type { AddOn } from '../../api/addons';
import { placeLocation } from '../../utils/format';

const MAX_TICKETS = 20;
const WINDOW_DAYS = 90;

interface Visitor {
  name: string;
  email: string;
  phone: string;
}

type BookingMode = 'individual' | 'group';

const isEducational = (t: GroupType): boolean => GROUP_TYPES.some((g) => g.value === t && g.educational);
const sumQty = (qty: Record<number, number>): number => Object.values(qty).reduce((a, b) => a + b, 0);
/** Picks the ".one" or ".other" form of a counted string. */
const plural = (t: WithI18nProps['i18n']['t'], key: string, n: number): string => t(`${key}.${n === 1 ? 'one' : 'other'}`, { n });

/** YouTube and Google Maps links in a form that can be shown in an iframe; null = open in a new tab instead. */
function tourEmbedUrl(raw: string): string | null {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  const host = url.hostname.replace(/^www\./, '').replace(/^m\./, '');
  if (host === 'youtu.be' || host.endsWith('youtube.com') || host === 'youtube-nocookie.com') {
    let id = '';
    if (host === 'youtu.be') id = url.pathname.slice(1);
    else if (url.searchParams.get('v')) id = url.searchParams.get('v') ?? '';
    else {
      const m = /^\/(embed|shorts|live)\/([^/?#]+)/.exec(url.pathname);
      id = m?.[2] ?? '';
    }
    if (!/^[\w-]{6,20}$/.test(id)) return null;
    const start = parseInt(url.searchParams.get('t') ?? url.searchParams.get('start') ?? '', 10);
    return `https://www.youtube-nocookie.com/embed/${id}?rel=0${start > 0 ? `&start=${start}` : ''}`;
  }
  const isMaps = (host.startsWith('google.') && url.pathname.startsWith('/maps')) || host.startsWith('maps.google.');
  if (isMaps) {
    if (url.pathname.startsWith('/maps/embed') || url.searchParams.get('output')?.includes('embed')) return raw;
    // Street View: ?api=1&map_action=pano&viewpoint=lat,lng, ?cbll=lat,lng or a /@lat,lng,3a,... path
    const latLng = /^(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)/;
    const point = url.searchParams.get('viewpoint') ?? url.searchParams.get('cbll') ?? '';
    const at = /@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)(,[^/]*)?/.exec(url.pathname);
    const pano = url.searchParams.get('map_action') === 'pano' || url.searchParams.get('layer') === 'c' || /,3a,/.test(at?.[3] ?? '');
    const m = latLng.exec(point) ?? (at ? [at[0], at[1], at[2]] : null);
    if (m && pano) return `https://www.google.com/maps?layer=c&cbll=${m[1]},${m[2]}&cbp=11,0,0,0,0&output=svembed`;
    if (m) return `https://maps.google.com/maps?q=${m[1]},${m[2]}&z=17&output=embed`;
    const q = url.searchParams.get('q') ?? url.searchParams.get('query');
    if (q) return `https://maps.google.com/maps?q=${encodeURIComponent(q)}&output=embed`;
    return null;
  }
  return null;
}

interface TourModalProps extends WithI18nProps {
  open: boolean;
  url: string;
  kind: string;
  name: string;
  onClose: () => void;
}

/** "Take a virtual tour": a React-controlled Bootstrap modal (no Bootstrap JS), like AuthModal. */
class TourModalBase extends React.Component<TourModalProps> {
  private listening = false;

  public componentDidMount(): void {
    if (this.props.open) this.attach();
  }

  public componentDidUpdate(): void {
    if (this.props.open) this.attach();
    else this.detach();
  }

  public componentWillUnmount(): void {
    this.detach();
  }

  private onKey = (e: KeyboardEvent): void => {
    if (e.key === 'Escape') this.props.onClose();
  };

  private attach(): void {
    if (this.listening) return;
    window.addEventListener('keydown', this.onKey);
    this.listening = true;
  }

  private detach(): void {
    if (!this.listening) return;
    window.removeEventListener('keydown', this.onKey);
    this.listening = false;
  }

  public render(): React.ReactNode {
    const { open, url, kind, name, onClose } = this.props;
    const { t } = this.props.i18n;
    if (!open) return null;
    const embed = tourEmbedUrl(url);
    return (
      <div className="modal show-react" role="dialog" aria-modal="true" aria-labelledby="tour-title" onClick={onClose}>
        <div className="modal-dialog modal-dialog-centered modal-xl">
          <div className="modal-content border-0 shadow" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3 id="tour-title" className="modal-title h5 mb-0">{t('giving.tour.title', { name })}</h3>
                {kind && <p className="small text-muted mb-0">{t(`giving.tour.kind.${kind}`)}</p>}
              </div>
              <button type="button" className="btn-close" aria-label={t('common.close')} onClick={onClose} />
            </div>
            <div className="modal-body p-0">
              {embed ? (
                <div className="ratio ratio-16x9 tour-frame">
                  <iframe
                    src={embed}
                    title={t('giving.tour.title', { name })}
                    allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture; fullscreen"
                    allowFullScreen
                    loading="lazy"
                    referrerPolicy="no-referrer-when-downgrade"
                  />
                </div>
              ) : (
                <div className="p-4 text-center">
                  <i className="bi bi-badge-vr display-4 text-primary" aria-hidden="true" />
                  <p className="mt-2">{t('giving.tour.external')}</p>
                </div>
              )}
            </div>
            <div className="modal-footer justify-content-between">
              <span className="small text-muted">{t('giving.tour.credit')}</span>
              <a href={url} target="_blank" rel="noreferrer" className={`btn ${embed ? 'btn-outline-primary' : 'btn-accent'}`}>
                <i className="bi bi-box-arrow-up-right me-1" aria-hidden="true" />
                {t('giving.tour.open')}
              </a>
            </div>
          </div>
        </div>
      </div>
    );
  }
}

const TourModal = withI18n(TourModalBase);

type MuseumDetailProps = WithRouterProps & WithAuthProps & WithI18nProps;

interface MuseumDetailState {
  museum: MuseumWithInfo | null | undefined;
  date: string;
  /** False until the visitor picks a date themselves (until then we may move it past closures). */
  dateTouched: boolean;
  closures: PublicClosure[];
  availability: AvailabilityInfo | null;
  slotId: number | null;
  qty: Record<number, number>;
  visitor: Visitor;
  error: string;
  submitting: boolean;
  authOpen: boolean;
  mode: BookingMode;
  groupType: GroupType;
  organisation: string;
  escorts: number;
  /** Upcoming events & shows at this place (events app). */
  events: EventSummary[];
  /** Optional extras offered at checkout (shown as a preview). */
  addons: AddOn[];
  tourOpen: boolean;
}

/** Booking switches: site-wide (Admin -> Settings) and this place's own (Admin -> Places). */
const individualOpen = (m: Museum): boolean => m.individual_open ?? m.allow_individual ?? true;
const groupsOpen = (m: Museum): boolean => m.groups_open ?? m.allow_groups;

class MuseumDetail extends React.Component<MuseumDetailProps, MuseumDetailState> {
  public state: MuseumDetailState = {
    museum: undefined,
    date: isoDate(1),
    dateTouched: false,
    closures: [],
    availability: null,
    slotId: null,
    qty: {},
    visitor: { name: '', email: '', phone: '' },
    error: '',
    submitting: false,
    authOpen: false,
    mode: 'individual',
    groupType: 'school',
    organisation: '',
    escorts: 0,
    events: [],
    addons: [],
    tourOpen: false,
  };

  private mounted = false;
  private museumRequest = 0;
  private availabilityRequest = 0;

  public componentDidMount(): void {
    this.mounted = true;
    this.loadMuseum();
    this.prefillVisitor();
    track('view_place', { museum: this.props.router.params.slug });
  }

  public componentDidUpdate(prevProps: MuseumDetailProps, prevState: MuseumDetailState): void {
    if (prevProps.router.params.slug !== this.props.router.params.slug) this.loadMuseum();
    if (prevProps.auth.user !== this.props.auth.user) this.prefillVisitor();
    // Only reload slots when the place or date changes, not when cached details are refreshed.
    if (prevState.museum?.slug !== this.state.museum?.slug || prevState.date !== this.state.date) this.reloadSlots();
    // Follow the booking switches: no group mode where groups are off, straight to groups where only groups are open.
    const m = this.state.museum;
    if (m && this.state.mode === 'group' && !groupsOpen(m)) this.setMode('individual');
    if (m && this.state.mode === 'individual' && !individualOpen(m) && groupsOpen(m)) this.setMode('group');
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private pendingSlot = 0;

  private loadMuseum(): void {
    const id = ++this.museumRequest;
    let first = true;
    const slug = this.props.router.params.slug;
    this.setState({ closures: [], dateTouched: false });
    cachedGet<MuseumWithInfo>(`/museums/${slug}/`, undefined, (m) => {
      if (!this.mounted || id !== this.museumRequest) return;
      this.setState({ museum: m });
      if (!first) return; // keep the visitor's chosen date when fresher data arrives
      first = false;
      // ?date=YYYY-MM-DD (e.g. from a waitlist "seats free" message) preselects that day.
      const wanted = this.props.router.searchParams.get('date') ?? '';
      if (/^\d{4}-\d{2}-\d{2}$/.test(wanted) && wanted >= isoDate(0)) this.setState({ date: wanted, dateTouched: true });
      else this.setState({ date: this.firstOpenDate(m, this.state.closures) });
      const wantedSlot = Number(this.props.router.searchParams.get('slot'));
      if (wantedSlot > 0) this.pendingSlot = wantedSlot; // applied once that day's slots load
    }).catch(() => {
      if (this.mounted && id === this.museumRequest) this.setState({ museum: null });
    });
    this.setState({ events: [] });
    cachedGet<EventSummary[]>('/events/', { museum: slug }, (events) => {
      if (this.mounted && id === this.museumRequest) this.setState({ events });
    }).catch(() => undefined);
    this.setState({ addons: [] });
    fetchPlaceAddOns(slug ?? '')
      .then((addons) => {
        if (this.mounted && id === this.museumRequest) this.setState({ addons });
      })
      .catch(() => undefined);
    cachedGet<PublicClosure[]>(`/museums/${slug}/closures/`, undefined, (closures) => {
      if (!this.mounted || id !== this.museumRequest) return;
      this.setState((s) => ({
        closures,
        // Move the suggested date past whole-day closures, unless the visitor already chose one.
        date: !s.dateTouched && s.museum ? this.firstOpenDate(s.museum, closures) : s.date,
      }));
    }).catch(() => undefined);
  }

  /** Whole-day closure covering an ISO date, if any. */
  private closureOn(day: string, closures: PublicClosure[] = this.state.closures): PublicClosure | undefined {
    return closures.find((c) => c.all_day && c.start_date <= day && day <= c.end_date);
  }

  /** First day from tomorrow that is neither the weekly closed day nor a whole-day closure. */
  private firstOpenDate(m: Museum, closures: PublicClosure[]): string {
    let offset = 1;
    while (
      offset < WINDOW_DAYS &&
      ((m.closed_weekday !== null && djangoWeekday(isoDate(offset)) === m.closed_weekday) || this.closureOn(isoDate(offset), closures))
    )
      offset++;
    return isoDate(offset);
  }

  /** Price of a ticket on the chosen date (seasonal / peak rules applied by the server). */
  private priceOf(tk: NonNullable<Museum['ticket_types']>[number]): { price: number; rule: string | null } {
    const p = this.state.availability?.prices?.find((x) => x.ticket_type === tk.id);
    return p ? { price: Number(p.price), rule: Number(p.price) !== Number(tk.price) ? p.rule : null } : { price: Number(tk.price), rule: null };
  }

  private prefillVisitor(): void {
    const { user } = this.props.auth;
    if (user) {
      this.setState((s) => ({
        visitor: {
          name: s.visitor.name || `${user.first_name} ${user.last_name}`.trim(),
          email: s.visitor.email || user.email,
          phone: s.visitor.phone || user.phone,
        },
      }));
    }
  }

  private reloadSlots(): void {
    const { museum } = this.state;
    if (!museum) return;
    this.setState({ availability: null, slotId: null });
    this.fetchAvailability(museum.slug, this.state.date);
  }

  private fetchAvailability(slug: string, date: string): void {
    const id = ++this.availabilityRequest;
    api.get<AvailabilityInfo>(`/museums/${slug}/availability/`, { params: { date } }).then((r) => {
      if (!this.mounted || id !== this.availabilityRequest) return;
      const pick = this.pendingSlot;
      this.pendingSlot = 0;
      this.setState((st) => ({ availability: r.data, slotId: pick && r.data.slots.some((x) => x.id === pick) ? pick : st.slotId }));
    });
  }

  private getTickets(): NonNullable<Museum['ticket_types']> {
    return (this.state.museum?.ticket_types ?? []).filter((t) => t.is_active);
  }

  private isGroup(s: MuseumDetailState = this.state): boolean {
    return s.mode === 'group' && !!s.museum && groupsOpen(s.museum);
  }

  private selectedSlot(s: MuseumDetailState = this.state): SlotAvailabilityInfo | undefined {
    return s.availability?.slots.find((x) => x.id === s.slotId);
  }

  /** Most tickets (paying participants in group mode) the current selection allows. */
  private participantCap(s: MuseumDetailState): number {
    const slot = this.selectedSlot(s);
    if (!this.isGroup(s)) return Math.min(MAX_TICKETS, slot?.available ?? MAX_TICKETS);
    const max = s.museum!.group_policy.max_size;
    return Math.max(0, Math.min(max, slot ? slot.group_available - s.escorts : max));
  }

  /** Free escorts allowed for this many participants (schools and colleges only). */
  private escortCap(s: MuseumDetailState, participants: number, groupType: GroupType): number {
    if (!this.isGroup(s) || !isEducational(groupType) || participants === 0) return 0;
    const cap = Math.ceil(participants / s.museum!.group_policy.escorts_per);
    const slot = this.selectedSlot(s);
    return Math.max(0, slot ? Math.min(cap, slot.group_available - participants) : cap);
  }

  private changeQty = (id: number, delta: number): void => this.setQty(id, (n) => n + delta);

  private typeQty = (id: number) => (e: React.ChangeEvent<HTMLInputElement>): void => {
    const n = parseInt(e.target.value, 10);
    this.setQty(id, () => (Number.isNaN(n) ? 0 : n));
  };

  /** Sets one ticket count within the remaining room, then keeps escorts within their allowance. */
  private setQty(id: number, next: (current: number) => number): void {
    this.setState((s) => {
      const current = s.qty[id] ?? 0;
      const room = this.participantCap(s) - (sumQty(s.qty) - current);
      const qty = { ...s.qty, [id]: Math.max(0, Math.min(next(current), Math.max(room, current))) };
      return { qty, escorts: Math.min(s.escorts, this.escortCap(s, sumQty(qty), s.groupType)) };
    });
  }

  private changeEscorts = (delta: number): void =>
    this.setState((s) => ({ escorts: Math.max(0, Math.min(s.escorts + delta, this.escortCap(s, sumQty(s.qty), s.groupType))) }));

  private setGroupType = (e: React.ChangeEvent<HTMLSelectElement>): void => {
    const groupType = e.target.value as GroupType;
    this.setState((s) => ({ groupType, escorts: Math.min(s.escorts, this.escortCap(s, sumQty(s.qty), groupType)) }));
  };

  /** Individual and group tickets are chosen differently, so switching starts the selection afresh. */
  private setMode = (mode: BookingMode): void => {
    if (mode === this.state.mode) return;
    this.setState({ mode, qty: {}, escorts: 0, slotId: null, error: '' });
  };

  private setVisitor = (k: keyof Visitor) => (e: React.ChangeEvent<HTMLInputElement>): void =>
    this.setState({ visitor: { ...this.state.visitor, [k]: e.target.value } });

  private book = (e: React.FormEvent): void => {
    e.preventDefault();
    // Browsing and choosing tickets is open to everyone; an account is only needed to hold the booking.
    if (!this.props.auth.user) this.setState({ authOpen: true });
    else this.createBooking();
  };

  private createBooking = async (): Promise<void> => {
    const { museum, slotId, date, qty, visitor, groupType, organisation, escorts } = this.state;
    const tickets = this.getTickets();
    const group = this.isGroup();
    this.setState({ authOpen: false, error: '', submitting: true });
    try {
      const payload = {
        museum: museum!.slug,
        slot: slotId,
        visit_date: date,
        items: tickets.map((t) => ({ ticket_type: t.id, quantity: qty[t.id!] ?? 0 })).filter((i) => i.quantity > 0),
        visitor_name: visitor.name,
        visitor_email: visitor.email,
        visitor_phone: visitor.phone,
      };
      const { data } = group
        ? await api.post<Booking>('/bookings/group/', {
            ...payload,
            group_type: groupType,
            organisation_name: organisation.trim(),
            escort_count: isEducational(groupType) ? escorts : 0,
          })
        : await api.post<Booking>('/bookings/', payload);
      this.props.router.navigate(data.status === 'confirmed' ? `/tickets/${data.reference}` : `/checkout/${data.reference}`);
    } catch (err) {
      if (!this.mounted) return;
      this.setState({ error: errorMessage(err) });
      this.fetchAvailability(museum!.slug, date);
    } finally {
      if (this.mounted) this.setState({ submitting: false });
    }
  };

  private renderGroupFields(museum: Museum): React.ReactNode {
    const { groupType, organisation } = this.state;
    const { t } = this.props.i18n;
    return (
      <div className="row g-2 mb-3">
        <div className="col-12">
          <label htmlFor="g-type" className="form-label">{t('place.group.type')}</label>
          <select id="g-type" className="form-select" value={groupType} onChange={this.setGroupType}>
            {GROUP_TYPES.map((g) => (
              <option key={g.value} value={g.value}>{t(`common.groupType.${g.value}`)}</option>
            ))}
          </select>
          <div className="form-text">
            {isEducational(groupType)
              ? museum.school_discount_percent > 0 && t('place.group.schoolDiscount', { n: museum.school_discount_percent })
              : museum.group_discount_percent > 0 && t('place.group.groupDiscount', { n: museum.group_discount_percent })}
          </div>
        </div>
        <div className="col-12">
          <label htmlFor="g-org" className="form-label">{isEducational(groupType) ? t('place.group.schoolName') : t('place.group.orgName')}</label>
          <input
            id="g-org"
            className="form-control"
            value={organisation}
            maxLength={200}
            onChange={(e) => this.setState({ organisation: e.target.value })}
            required
          />
        </div>
      </div>
    );
  }

  /** Coloured dot plus a text label (never colour alone). */
  private renderCrowd(s: SlotAvailabilityInfo): React.ReactNode {
    if (!s.crowd || s.closed_reason) return null;
    const { t } = this.props.i18n;
    const level = t(`placeinfo.crowd.${s.crowd}`);
    return (
      <small className="d-flex align-items-center justify-content-center gap-1" title={t('placeinfo.crowd.label', { level })}>
        <span className={`d-inline-block rounded-circle border border-light ${CROWD_DOT[s.crowd]}`} style={{ width: 9, height: 9 }} aria-hidden="true" />
        <span className="visually-hidden">{t('placeinfo.crowd.label', { level })}</span>
        <span aria-hidden="true">{level}</span>
      </small>
    );
  }

  private renderTicketPrice(tk: NonNullable<Museum['ticket_types']>[number]): React.ReactNode {
    const { t } = this.props.i18n;
    const { price, rule } = this.priceOf(tk);
    return (
      <div className="text-muted small">
        {price === 0 ? t('common.free') : formatPrice(price)}
        {rule && (
          <>
            {' '}
            <s className="ms-1" title={t('placeinfo.price.was', { price: formatPrice(tk.price) })}>
              <span className="visually-hidden">{t('placeinfo.price.was', { price: formatPrice(tk.price) })}</span>
              <span aria-hidden="true">{formatPrice(tk.price)}</span>
            </s>
            <div className="text-accent">
              <i className="bi bi-tag me-1" aria-hidden="true" />
              {t('placeinfo.price.special', { rule })}
            </div>
          </>
        )}
      </div>
    );
  }

  private renderClosures(): React.ReactNode {
    const { closures } = this.state;
    const { t } = this.props.i18n;
    const today = isoDate(0);
    const upcoming = closures.filter((c) => c.end_date >= today).slice(0, 5);
    if (upcoming.length === 0) return null;
    const range = (c: PublicClosure): string =>
      c.start_date === c.end_date
        ? formatDate(c.start_date, { weekday: 'short', day: 'numeric', month: 'short' })
        : `${formatDate(c.start_date, { day: 'numeric', month: 'short' })} – ${formatDate(c.end_date, { day: 'numeric', month: 'short', year: 'numeric' })}`;
    return (
      <div className="card border-0 bg-light mb-4">
        <div className="card-body py-3">
          <h3 className="h6 mb-2">
            <i className="bi bi-calendar-x text-accent me-2" aria-hidden="true" />
            {t('placeinfo.closures.title')}
          </h3>
          <ul className="list-unstyled small mb-1">
            {upcoming.map((c) => (
              <li key={c.id} className="d-flex flex-wrap gap-2 py-1">
                <strong>{range(c)}</strong>
                <span>{c.reason}</span>
                <span className="text-muted">
                  {c.all_day
                    ? t('placeinfo.closures.allDay')
                    : t('placeinfo.closures.slots', { times: c.slots.map((s) => formatTime(s.start_time)).join(', ') })}
                </span>
              </li>
            ))}
          </ul>
          <div className="text-muted small">{t('placeinfo.closures.more')}</div>
        </div>
      </div>
    );
  }

  /** "Upcoming events at this place": light & sound shows, walks... each linking to /events/<slug>. */
  /** "Add to your visit": a preview of the extras visitors can pick at checkout. */
  private renderAddOns(): React.ReactNode {
    const { addons } = this.state;
    const { t } = this.props.i18n;
    if (!addons.length) return null;
    return (
      <div className="mb-4">
        <h3 className="mb-1">{t('shop.addons.title')}</h3>
        <p className="small text-muted mb-2">{t('shop.addons.intro')}</p>
        <div className="d-flex flex-wrap gap-2">
          {addons.map((a) => (
            <span key={a.id} className="addon-chip" title={a.description || undefined}>
              <i className={`bi bi-${a.icon}`} aria-hidden="true" />
              <span>{a.name}</span>
              <span className="text-muted">
                {Number(a.price) === 0 ? t('shop.addons.free') : `${formatINR(a.price)} ${t(a.per === 'person' ? 'shop.addons.perPerson' : 'shop.addons.perBooking')}`}
              </span>
            </span>
          ))}
        </div>
      </div>
    );
  }

  private renderEvents(): React.ReactNode {
    const { events } = this.state;
    const { t } = this.props.i18n;
    if (events.length === 0) return null;
    return (
      <section className="mb-4" aria-labelledby="place-events">
        <h3 id="place-events">{t('events.atPlace')}</h3>
        <div className="list-group shadow-sm">
          {events.map((e) => (
            <Link key={e.id} to={`/events/${e.slug}`} className="list-group-item list-group-item-action d-flex justify-content-between align-items-center gap-2">
              <span>
                <i className={`bi ${KIND_ICONS[e.kind]} text-accent me-2`} aria-hidden="true" />
                <strong>{e.title}</strong>
                <span className="d-block small text-muted">
                  {t(`events.kind.${e.kind}`)}
                  {e.next_date && <> · {t('events.next', { date: formatDate(e.next_date, { weekday: 'short', day: 'numeric', month: 'short' }) })}</>}
                </span>
              </span>
              {e.from_price !== null && (
                <span className="text-nowrap small">{Number(e.from_price) === 0 ? t('common.free') : t('events.fromPrice', { price: formatINR(e.from_price) })}</span>
              )}
            </Link>
          ))}
        </div>
      </section>
    );
  }

  private renderVisitorInfo(museum: MuseumWithInfo): React.ReactNode {
    const { t } = this.props.i18n;
    const f = museum.facilities ?? {};
    const flags = FACILITY_FLAGS.filter((x) => f[x.key]);
    const texts = FACILITY_TEXTS.filter((x) => (f[x.key] ?? '').trim());
    const minutes = f.avg_visit_minutes ?? 0;
    if (flags.length === 0 && texts.length === 0 && !f.photography && !minutes) return null;
    const duration =
      minutes >= 60
        ? t('placeinfo.info.hours', { h: Math.floor(minutes / 60), m: minutes % 60 })
        : t('placeinfo.info.minutes', { n: minutes });
    return (
      <>
        <h3 className="mt-4">{t('placeinfo.info.title')}</h3>
        <div className="card border-0 shadow-sm mb-4">
          <div className="card-body">
            {flags.length > 0 && (
              <>
                <h4 className="h6 text-muted">{t('placeinfo.info.facilities')}</h4>
                <ul className="list-unstyled row g-2 mb-3">
                  {flags.map((x) => (
                    <li key={x.key} className="col-sm-6 col-md-4 d-flex align-items-center gap-2">
                      <i className={`bi ${x.icon} text-primary`} aria-hidden="true" />
                      <span>{t(`placeinfo.info.${x.key}`)}</span>
                      <i className="bi bi-check2 text-success" aria-label={t('placeinfo.info.available')} />
                    </li>
                  ))}
                </ul>
              </>
            )}
            <dl className="row mb-0 small">
              {f.photography && (
                <>
                  <dt className="col-sm-4"><i className="bi bi-camera me-2 text-primary" aria-hidden="true" />{t('placeinfo.info.photography')}</dt>
                  <dd className="col-sm-8">{t(`placeinfo.photo.${f.photography}`)}</dd>
                </>
              )}
              {minutes > 0 && (
                <>
                  <dt className="col-sm-4"><i className="bi bi-stopwatch me-2 text-primary" aria-hidden="true" />{t('placeinfo.info.avg_visit_minutes')}</dt>
                  <dd className="col-sm-8">{duration}</dd>
                </>
              )}
              {texts.map((x) => (
                <React.Fragment key={x.key}>
                  <dt className="col-sm-4"><i className={`bi ${x.icon} me-2 text-primary`} aria-hidden="true" />{t(`placeinfo.info.${x.key}`)}</dt>
                  <dd className="col-sm-8" style={{ whiteSpace: 'pre-line' }}>{f[x.key]}</dd>
                </React.Fragment>
              ))}
            </dl>
          </div>
        </div>
      </>
    );
  }

  public render(): React.ReactNode {
    const { user } = this.props.auth;
    const { t } = this.props.i18n;
    const { museum, date, availability, slotId, qty, visitor, error, submitting, authOpen, mode, groupType, escorts, closures } = this.state;

    const tickets = this.getTickets();
    // Listed places (no tickets or slots yet) show an information card instead of the booking form.
    const infoOnly = !!museum && (tickets.length === 0 || !(museum.slots ?? []).some((sl) => sl.is_active));
    const selectedSlot = this.selectedSlot();
    const count = sumQty(qty);
    // Seasonal / peak prices for the chosen date (base prices until availability arrives).
    const total = tickets.reduce((sum, tk) => sum + this.priceOf(tk).price * (qty[tk.id!] ?? 0), 0);
    const pricesVary = (availability?.prices ?? []).some((p) => Number(p.price) !== Number(p.base_price));
    const dayClosure = this.closureOn(date, closures);

    if (museum === undefined) return <Loader />;
    if (museum === null)
      return (
        <div className="container page py-4 py-lg-5">
          <Empty title={t('place.notFound')}>
            <Link to="/museums" className="btn btn-outline-primary">{t('place.explorePlaces')}</Link>
          </Empty>
        </div>
      );

    const group = this.isGroup();
    const policy = museum.group_policy;
    const maxQty = this.participantCap(this.state);
    const educational = group && isEducational(groupType);
    const maxEscorts = this.escortCap(this.state, count, groupType);
    const people = count + (educational ? escorts : 0);
    // Display only: the server recalculates the price when the booking is created.
    const discountPercent = !group ? 0 : educational ? museum.school_discount_percent : museum.group_discount_percent;
    const discount = Math.round((total * discountPercent) / 100);
    const groupTotal = total - discount;
    // A group slot must fit everyone chosen so far, or at least the smallest allowed group.
    const groupNeeded = Math.max(people, policy?.min_size ?? 0);
    const groupReady = group && count >= policy.min_size && count <= policy.max_size;

    const highlights = museum.highlights.split('\n').filter(Boolean);

    return (
      <div className="container page py-4 py-lg-5">
        <PhotoCarousel museum={museum}>
          <div className="d-flex flex-wrap gap-2 mb-2">
            <span className={`badge ${museum.place_type === 'museum' ? 'bg-primary' : 'bg-accent'}`}>
              {t(`common.type.${museum.place_type}`)}
            </span>
            {museum.category_name && <span className="badge bg-light text-dark">{museum.category_name}</span>}
          </div>
          <h1 className="display-5 mb-1">{museum.name}</h1>
          <div>
            <i className="bi bi-geo-alt-fill me-1" aria-hidden="true" />
            {placeLocation(museum.city_name, museum.state_name)}
          </div>
        </PhotoCarousel>

        <div className="row g-4">
          <div className="col-lg-8">
            {museum.tagline && <p className="lead text-secondary">{museum.tagline}</p>}
            {museum.virtual_tour_url && (
              <button type="button" className="btn btn-outline-primary mb-3 tour-btn" onClick={() => this.setState({ tourOpen: true })}>
                <i className={`bi ${museum.virtual_tour_kind === 'video' ? 'bi-play-circle' : 'bi-badge-vr'} me-2`} aria-hidden="true" />
                {t('giving.tour.button')}
              </button>
            )}
            <Description museum={museum} />

            <div className="row g-2 my-4">
              {!infoOnly && (<>
              <div className="col-sm-6 col-md-3">
                <div className="fact">
                  <span className="label"><i className="bi bi-clock me-1" aria-hidden="true" />{t('place.fact.timings')}</span>
                  <strong>{formatTime(museum.opening_time)} – {formatTime(museum.closing_time)}</strong>
                </div>
              </div>
              <div className="col-sm-6 col-md-3">
                <div className="fact">
                  <span className="label"><i className="bi bi-calendar-x me-1" aria-hidden="true" />{t('place.fact.closedOn')}</span>
                  <strong>{museum.closed_weekday === null ? t('place.fact.openAllWeek') : t(`common.weekday.${museum.closed_weekday}`)}</strong>
                </div>
              </div>
              </>)}
              {museum.established_year && (
                <div className="col-sm-6 col-md-3">
                  <div className="fact">
                    <span className="label"><i className="bi bi-hourglass-split me-1" aria-hidden="true" />{t('place.fact.established')}</span>
                    <strong>{museum.established_year}</strong>
                  </div>
                </div>
              )}
              {museum.avg_rating && (
                <div className="col-sm-6 col-md-3">
                  <a href="#reviews" className="fact d-block text-decoration-none text-body">
                    <span className="label"><i className="bi bi-star-fill me-1" aria-hidden="true" />{t('place.fact.rating')}</span>
                    <strong><Stars value={museum.avg_rating} /> {museum.avg_rating.toFixed(1)} ({museum.review_count})</strong>
                  </a>
                </div>
              )}
            </div>

            {this.renderClosures()}

            {this.renderEvents()}

            {this.renderAddOns()}

            {highlights.length > 0 && (
              <>
                <h3>{t('place.highlights')}</h3>
                <ul className="list-unstyled mb-4">
                  {highlights.map((h) => (
                    <li key={h} className="d-flex gap-2 mb-2">
                      <i className="bi bi-check2-circle text-accent" aria-hidden="true" />
                      <span>{h}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}

            {!infoOnly && (<>
            <h3 className="mt-4">{t('place.prices.title')}</h3>
            <div className="card border-0 shadow-sm mb-4">
              <div className="table-responsive">
                <table className="table table-hover align-middle mb-0">
                  <thead><tr><th>{t('place.prices.visitorType')}</th><th>{t('place.prices.notes')}</th><th className="text-end">{t('place.prices.price')}</th></tr></thead>
                  <tbody>
                    {tickets.map((tk) => (
                      <tr key={tk.id}><td>{tk.name}</td><td className="text-muted">{tk.description}</td><td className="text-end">{Number(tk.price) === 0 ? t('common.free') : formatPrice(tk.price)}<FxHint amount={tk.price} className="d-block" /></td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            {pricesVary && (
              <p className="text-muted small mt-n2 mb-4">
                <i className="bi bi-tag me-1" aria-hidden="true" />
                {t('placeinfo.price.dateNote')}
              </p>
            )}
            </>)}

            {this.renderVisitorInfo(museum)}

            <h3 className="mt-4">{t('place.gettingThere')}</h3>
            <p>{museum.address}</p>
            {museum.latitude && museum.longitude && (
              <a href={`https://www.google.com/maps/search/?api=1&query=${museum.latitude},${museum.longitude}`} target="_blank" rel="noreferrer">
                <i className="bi bi-map me-1" aria-hidden="true" />
                {t('place.openMaps')}
              </a>
            )}
            {museum.managed_by && <p className="text-muted small mt-3">{t('place.managedBy', { name: museum.managed_by })}</p>}

            <Reviews slug={museum.slug} museumName={museum.name} />
          </div>

          <div className="col-lg-4">
            <div className="booking-panel">
              {infoOnly ? (
                <div className="card border-0 shadow">
                  <div className="card-body p-4">
                    <i className="bi bi-info-circle fs-2 text-accent" aria-hidden="true" />
                    <h2 className="h5 mt-2">{t('place.infoOnly.title')}</h2>
                    <p className="text-muted">{t('place.infoOnly.body')}</p>
                    <div className="d-grid gap-2">
                      {museum.contact_phone && (
                        <a className="btn btn-outline-primary" href={`tel:${museum.contact_phone.replace(/\s/g, '')}`}>
                          <i className="bi bi-telephone me-1" aria-hidden="true" />{t('place.infoOnly.call')} {museum.contact_phone}
                        </a>
                      )}
                      {museum.latitude && museum.longitude && (
                        <a className="btn btn-outline-primary" target="_blank" rel="noreferrer"
                          href={`https://www.google.com/maps/dir/?api=1&destination=${museum.latitude},${museum.longitude}`}>
                          <i className="bi bi-signpost-2 me-1" aria-hidden="true" />{t('place.infoOnly.directions')}
                        </a>
                      )}
                    </div>
                    <p className="small text-muted mt-3 mb-0">
                      <i className="bi bi-shield-exclamation me-1" aria-hidden="true" />{t('place.infoOnly.unverified')}
                    </p>
                  </div>
                </div>
              ) : !individualOpen(museum) && !groupsOpen(museum) ? (
                <div className="card border-0 shadow">
                  <div className="card-body p-4 text-center">
                    <i className="bi bi-pause-circle fs-1 text-accent" aria-hidden="true" />
                    <h2 className="h5 mt-2">{t('place.paused.title')}</h2>
                    {museum.groups_paused_message && <p className="mb-2">{museum.groups_paused_message}</p>}
                    <p className="small text-muted mb-0">{t('place.paused.counter')}</p>
                  </div>
                </div>
              ) : (
              <form className="card border-0 shadow" onSubmit={this.book}>
                <div className="card-body p-4">
                  {!individualOpen(museum) && (
                    <div className="d-flex align-items-center gap-2 mb-3">
                      <span className="badge bg-accent"><i className="bi bi-people me-1" aria-hidden="true" />{t('place.groupsOnly')}</span>
                      {museum.groups_paused_message && <span className="small text-muted">{museum.groups_paused_message}</span>}
                    </div>
                  )}
                  {groupsOpen(museum) && individualOpen(museum) && (
                    <div className="btn-group w-100 mb-3" role="group" aria-label={t('place.mode.label')}>
                      <button type="button" className={`btn ${mode === 'individual' ? 'btn-primary' : 'btn-outline-primary'}`} aria-pressed={mode === 'individual'} onClick={() => this.setMode('individual')}>
                        <i className="bi bi-person me-1" aria-hidden="true" />
                        {t('place.mode.individual')}
                      </button>
                      <button type="button" className={`btn ${mode === 'group' ? 'btn-primary' : 'btn-outline-primary'}`} aria-pressed={mode === 'group'} onClick={() => this.setMode('group')}>
                        <i className="bi bi-people me-1" aria-hidden="true" />
                        {t('place.mode.group', { min: policy.min_size, max: policy.max_size })}
                      </button>
                    </div>
                  )}
                  <h3 className="h4 mb-3">{group ? t('place.book.groupTitle') : t('place.book.title')}</h3>
                  {error && <div className="alert alert-danger">{error}</div>}

                  {group && this.renderGroupFields(museum)}

                  <div className="mb-3">
                    <label htmlFor="visit-date" className="form-label">{t('place.date')}</label>
                    <input id="visit-date" type="date" className="form-control" value={date} min={isoDate(0)} max={isoDate(WINDOW_DAYS)} onChange={(e) => this.setState({ date: e.target.value, dateTouched: true })} required />
                    {dayClosure && !availability?.closed && (
                      <div className="form-text text-danger" role="alert">
                        <i className="bi bi-calendar-x me-1" aria-hidden="true" />
                        {t('placeinfo.closed.day', { reason: dayClosure.reason })}
                      </div>
                    )}
                  </div>

                  <div className="mb-3">
                    <label className="form-label">{t('place.slot')}</label>
                    {!availability ? (
                      <Loader />
                    ) : availability.closed ? (
                      <div className="alert alert-warning mb-0">
                        {availability.closure_reason
                          ? t('placeinfo.closed.day', { reason: availability.closure_reason })
                          : t('place.slot.closed', { day: t(`common.weekday.${museum.closed_weekday ?? 0}`) })}
                      </div>
                    ) : !availability.bookable ? (
                      <div className="alert alert-warning mb-0">{t('place.slot.window', { n: WINDOW_DAYS })}</div>
                    ) : availability.slots.length === 0 ? (
                      <div className="alert alert-info mb-0">{t('place.slot.none')}</div>
                    ) : (
                      <div className="row g-2">
                        {availability.slots.map((s) => (
                          <div key={s.id} className="col-6">
                            {group ? (
                              <button
                                type="button"
                                className={`btn slot-btn w-100 ${slotId === s.id ? 'btn-primary' : 'btn-outline-primary'}`}
                                aria-pressed={slotId === s.id}
                                disabled={!s.bookable || s.group_available < groupNeeded}
                                onClick={() => { this.setState({ slotId: s.id }); track('select_slot', { museum: this.props.router.params.slug }); }}
                              >
                                <strong>{formatTime(s.start_time)}</strong>
                                <small>
                                  {s.closed_reason
                                    ? t('placeinfo.closed.slot')
                                    : !s.bookable && s.available > 0
                                      ? t('place.slot.started')
                                      : s.group_available === 0
                                        ? t('place.slot.noGroup')
                                        : plural(t, 'place.slot.groupLeft', s.group_available)}
                                </small>
                                {this.renderCrowd(s)}
                              </button>
                            ) : (
                              <button
                                type="button"
                                className={`btn slot-btn w-100 ${slotId === s.id ? 'btn-primary' : 'btn-outline-primary'}`}
                                aria-pressed={slotId === s.id}
                                disabled={!s.bookable}
                                onClick={() => { this.setState({ slotId: s.id }); track('select_slot', { museum: this.props.router.params.slug }); }}
                              >
                                <strong>{formatTime(s.start_time)}</strong>
                                <small className={s.available > 0 && s.available <= 10 && slotId !== s.id ? 'text-accent' : undefined}>
                                  {s.closed_reason ? t('placeinfo.closed.slot') : !s.bookable && s.available > 0 ? t('place.slot.started') : s.available === 0 ? t('place.slot.soldOut') : t('place.slot.left', { n: s.available })}
                                </small>
                                {this.renderCrowd(s)}
                              </button>
                            )}
                            {!group && s.available === 0 && !s.closed_reason && (
                              <WaitlistButton
                                target={{ museum: museum.slug, slot: s.id, visit_date: date }}
                                label={`${museum.name}, ${formatDate(date, { day: 'numeric', month: 'short' })} ${formatTime(s.start_time)}`}
                                className="mt-1"
                              />
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="mb-3">
                    <span className="form-label d-block mb-1">{group ? t('place.participants') : t('place.tickets')}</span>
                    {tickets.map((tk) => (
                      <div key={tk.id} className="d-flex justify-content-between align-items-center py-2 border-bottom">
                        <div>
                          <div className="fw-semibold">{tk.name}</div>
                          {this.renderTicketPrice(tk)}
                        </div>
                        <div className="input-group input-group-sm flex-nowrap" style={{ width: 110 }}>
                          <button type="button" className="btn btn-outline-primary" aria-label={t('place.qty.fewer', { name: tk.name })} disabled={!qty[tk.id!]} onClick={() => this.changeQty(tk.id!, -1)}>−</button>
                          {group ? (
                            <input
                              type="number"
                              className="form-control text-center px-1"
                              aria-label={t('place.qty.number', { name: tk.name })}
                              min={0}
                              max={maxQty}
                              value={qty[tk.id!] ?? 0}
                              onChange={this.typeQty(tk.id!)}
                            />
                          ) : (
                            <span className="form-control text-center bg-white" aria-live="polite">{qty[tk.id!] ?? 0}</span>
                          )}
                          <button type="button" className="btn btn-outline-primary" aria-label={t('place.qty.more', { name: tk.name })} disabled={count >= maxQty} onClick={() => this.changeQty(tk.id!, 1)}>+</button>
                        </div>
                      </div>
                    ))}
                    {group && (
                      <div className={`small mt-2 ${count < policy.min_size ? 'text-accent' : 'text-muted'}`} aria-live="polite">
                        {count < policy.min_size
                          ? count > 0
                            ? t('place.group.minimumMore', { min: policy.min_size, n: policy.min_size - count })
                            : t('place.group.minimum', { min: policy.min_size })
                          : t('place.group.ofUpTo', { n: count, max: policy.max_size })}
                      </div>
                    )}
                    {!group && groupsOpen(museum) && count >= MAX_TICKETS && (
                      <div className="small text-muted mt-2">
                        {t('place.group.bringing', { n: policy.min_size })}{' '}
                        <button type="button" className="btn btn-link btn-sm p-0 align-baseline" onClick={() => this.setMode('group')}>{t('place.group.bookAsGroup')}</button>
                      </div>
                    )}
                  </div>

                  {educational && (
                    <div className="mb-3">
                      <div className="d-flex justify-content-between align-items-center py-2 border-bottom">
                        <div>
                          <div className="fw-semibold">{t('place.escorts.title')}</div>
                          <div className="text-muted small">{t('place.escorts.rule', { n: policy.escorts_per })}</div>
                        </div>
                        <div className="input-group input-group-sm flex-nowrap" style={{ width: 110 }}>
                          <button type="button" className="btn btn-outline-primary" aria-label={t('place.escorts.fewer')} disabled={escorts === 0} onClick={() => this.changeEscorts(-1)}>−</button>
                          <span className="form-control text-center bg-white" aria-live="polite">{escorts}</span>
                          <button type="button" className="btn btn-outline-primary" aria-label={t('place.escorts.more')} disabled={escorts >= maxEscorts} onClick={() => this.changeEscorts(1)}>+</button>
                        </div>
                      </div>
                      {count > 0 && <div className="text-muted small mt-1">{t('place.escorts.upTo', { escorts: plural(t, 'common.group.escorts', maxEscorts), students: plural(t, 'place.students', count) })}</div>}
                    </div>
                  )}

                  {count > 0 && (
                    <div className="mb-2">
                      <div className="mb-3">
                        <label htmlFor="v-name" className="form-label">{group ? t('place.visitor.leaderName') : t('place.visitor.name')}</label>
                        <input id="v-name" className="form-control" value={visitor.name} onChange={this.setVisitor('name')} required />
                      </div>
                      <div className="mb-3">
                        <label htmlFor="v-email" className="form-label">{group ? t('place.visitor.leaderEmail') : t('place.visitor.email')}</label>
                        <input id="v-email" type="email" className="form-control" value={visitor.email} onChange={this.setVisitor('email')} required />
                      </div>
                      <div className="mb-3">
                        <label htmlFor="v-phone" className="form-label">{group ? t('place.visitor.leaderPhone') : t('place.visitor.phone')}</label>
                        <input id="v-phone" className="form-control" inputMode="tel" pattern="\+?[0-9]{10,13}" placeholder="9876543210" value={visitor.phone} onChange={this.setVisitor('phone')} required />
                      </div>
                    </div>
                  )}

                  {group ? (
                    <>
                      <div className="my-3">
                        <div className="d-flex justify-content-between py-1">
                          <span>{t('place.price.subtotal', { what: plural(t, 'place.participantsCount', count) })}</span>
                          <span>{formatINR(total)}</span>
                        </div>
                        {discountPercent > 0 && (
                          <div className="d-flex justify-content-between py-1 text-success">
                            <span>{t('common.group.discount', { n: discountPercent })}</span>
                            <span>−{formatINR(discount)}</span>
                          </div>
                        )}
                        {educational && escorts > 0 && (
                          <div className="d-flex justify-content-between py-1">
                            <span>{plural(t, 'common.group.escorts', escorts)}</span>
                            <span className="text-success">{t('common.free')}</span>
                          </div>
                        )}
                        <div className="d-flex justify-content-between fs-5 fw-bold border-top pt-2 mt-1">
                          <span>{t('place.price.total', { what: plural(t, 'place.people', people) })}</span>
                          <span className="text-end">{formatINR(groupTotal)}<FxHint amount={groupTotal} className="d-block fw-normal" /></span>
                        </div>
                      </div>
                      <button className="btn btn-accent btn-lg w-100" disabled={!slotId || !groupReady || submitting}>
                        {submitting ? t('place.reserving') : count > 0 ? t('place.bookForPeople', { n: people }) : t('place.bookGroup')}
                      </button>
                    </>
                  ) : (
                    <>
                      <div className="d-flex justify-content-between fs-5 fw-bold my-3">
                        <span>{plural(t, 'place.price.totalTickets', count)}</span>
                        <span className="text-end">{formatINR(total)}<FxHint amount={total} className="d-block fw-normal" /></span>
                      </div>
                      <button className="btn btn-accent btn-lg w-100" disabled={!slotId || count === 0 || submitting}>
                        {submitting ? t('place.reserving') : total === 0 && count > 0 ? t('place.freeTickets') : t('place.continuePay')}
                      </button>
                    </>
                  )}
                  {!user && count > 0 && (
                    <p className="text-muted small text-center mt-2 mb-0">
                      {t('place.loginHint')}
                    </p>
                  )}
                  {selectedSlot && (
                    <p className="text-muted small text-center mt-2 mb-0">
                      <i className="bi bi-calendar-event me-1" aria-hidden="true" />
                      {formatDate(date, { weekday: 'short', day: 'numeric', month: 'short' })}, {formatTime(selectedSlot.start_time)} – {formatTime(selectedSlot.end_time)}
                    </p>
                  )}
                  {selectedSlot && (selectedSlot.entered_so_far ?? 0) > 0 && (
                    <p className="text-muted small text-center mt-1 mb-0">
                      <i className="bi bi-people me-1" aria-hidden="true" />
                      {t('placeinfo.crowd.entered', { n: selectedSlot.entered_so_far ?? 0 })}
                    </p>
                  )}
                </div>
              </form>
              )}
              {groupsOpen(museum) && (
                <p className="text-muted small mt-2 mb-0 px-1">
                  <i className="bi bi-info-circle me-1" aria-hidden="true" />
                  {t('place.groupsNote', { n: policy.slot_share_percent })}
                </p>
              )}
              <div className="d-flex flex-wrap gap-2 mt-1 px-1">
                {museum.group_requests_open !== false && museum.allow_groups && (
                  <Link to={`/group-request/${museum.slug}`} className="btn btn-link btn-sm p-0 text-decoration-none">
                    <i className="bi bi-people me-1" aria-hidden="true" />
                    {t('place.requestGroup', { n: policy.max_size })}
                  </Link>
                )}
                <Link to={`/contact?topic=data&place=${encodeURIComponent(museum.slug)}`} className="btn btn-link btn-sm p-0 text-decoration-none text-muted">
                  <i className="bi bi-flag me-1" aria-hidden="true" />
                  {t('place.report')}
                </Link>
              </div>
              <div className="card border-0 shadow-sm support-card mt-3">
                <div className="card-body d-flex gap-3 align-items-start">
                  <i className="bi bi-heart-fill text-accent fs-4" aria-hidden="true" />
                  <div>
                    <h2 className="h6 mb-1">{t('giving.support.title')}</h2>
                    <p className="small text-muted mb-2">{t('giving.support.text', { name: museum.name })}</p>
                    <Link to={`/donate?museum=${encodeURIComponent(museum.slug)}`} className="btn btn-sm btn-accent">
                      <i className="bi bi-gift me-1" aria-hidden="true" />
                      {t('giving.support.cta')}
                    </Link>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <AuthModal
          open={authOpen}
          title={t('place.auth.title')}
          reason={
            group
              ? t('place.auth.groupReason', { n: people })
              : plural(t, 'place.auth.reason', count)
          }
          prefill={visitor}
          onClose={() => this.setState({ authOpen: false })}
          onDone={this.createBooking}
        />
        {museum.virtual_tour_url && (
          <TourModal
            open={this.state.tourOpen}
            url={museum.virtual_tour_url}
            kind={museum.virtual_tour_kind ?? ''}
            name={museum.name}
            onClose={() => this.setState({ tourOpen: false })}
          />
        )}
      </div>
    );
  }
}

export default withRouter(withAuth(withI18n(MuseumDetail)));
