import * as React from 'react';
import { Link, Navigate } from 'react-router-dom';
import { cachedGet } from '../../api/cache';
import { api, errorMessage } from '../../api/client';
import {
  GROUP_REQUEST_MAX,
  GroupRequest,
  GroupRequestInput,
  groupRequestStatus,
  PREFERRED_TIMES,
  PreferredTime,
} from '../../api/groupRequests';
import type { PublicClosure } from '../../api/placeinfo';
import { GROUP_TYPES } from '../../api/types';
import type { GroupType, Museum, Paginated } from '../../api/types';
import { Empty, Loader, Pagination, StatusBadge } from '../../components/Common';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { withI18n, WithI18nProps } from '../../i18n';
import { djangoWeekday, formatDate, formatDateTime, formatINR, formatTime, isoDate, WEEKDAYS } from '../../utils/format';
import { withRouter, WithRouterProps } from '../../utils/withRouter';

const MIN_LEAD_DAYS = 3;
const WINDOW_DAYS = 90;
const MAX_GROUP_DEFAULT = 60;

const isEducational = (t: GroupType): boolean => GROUP_TYPES.some((g) => g.value === t && g.educational);

type GroupRequestPageProps = WithRouterProps & WithAuthProps & WithI18nProps;

/** GET /group-requests/quote/: the group's estimated price on a date (weekend / holiday / season prices). */
interface GroupQuote {
  date: string;
  closed: string | null;
  closed_weekly: boolean;
  closed_reason: string;
  ticket_type: { id: number; name: string; base_price: string; price: string; rule: string | null } | null;
  participants: number;
  unit_price: string;
  base_unit_price: string;
  price_rule: string | null;
  subtotal: string;
  discount_percent: number;
  discount: string;
  total: string;
}

interface FormState {
  preferredDate: string;
  alternativeDate: string;
  preferredTime: PreferredTime;
  groupType: GroupType;
  organisation: string;
  contactName: string;
  contactEmail: string;
  contactPhone: string;
  participants: string;
  escorts: string;
  needsGuide: boolean;
  notes: string;
}

interface GroupRequestPageState {
  museum: Museum | null;
  museumError: string;
  form: FormState;
  submitting: boolean;
  error: string;
  created: GroupRequest | null;
  requests: Paginated<GroupRequest> | null;
  page: number;
  busyId: number | null;
  listError: string;
  /** Whole-day closures (holidays etc.) of this place, to warn before submitting. */
  closures: PublicClosure[];
  quote: GroupQuote | null;
  quoteLoading: boolean;
}

/** Large group visit request (more than the instant-group maximum) plus the visitor's existing requests. */
class GroupRequestPage extends React.Component<GroupRequestPageProps, GroupRequestPageState> {
  public state: GroupRequestPageState = {
    museum: null,
    museumError: '',
    form: {
      preferredDate: '',
      alternativeDate: '',
      preferredTime: 'any',
      groupType: 'school',
      organisation: '',
      contactName: '',
      contactEmail: '',
      contactPhone: '',
      participants: '',
      escorts: '0',
      needsGuide: false,
      notes: '',
    },
    submitting: false,
    error: '',
    created: null,
    requests: null,
    page: 1,
    busyId: null,
    listError: '',
    closures: [],
    quote: null,
    quoteLoading: false,
  };

  private mounted = false;
  private quoteTimer: ReturnType<typeof setTimeout> | undefined;
  private quoteRequest = 0;
  private prefilled = false;

  public componentDidMount(): void {
    this.mounted = true;
    this.loadMuseum();
    this.prefill();
    if (this.props.auth.user) this.loadRequests();
  }

  public componentDidUpdate(prevProps: GroupRequestPageProps, prevState: GroupRequestPageState): void {
    if (prevProps.router.params.slug !== this.props.router.params.slug) this.loadMuseum();
    if (!prevProps.auth.user && this.props.auth.user) {
      this.prefill();
      this.loadRequests();
    }
    if (prevState.page !== this.state.page) this.loadRequests();
    const f = this.state.form;
    const pf = prevState.form;
    if (
      f.preferredDate !== pf.preferredDate || f.participants !== pf.participants || f.groupType !== pf.groupType ||
      this.state.museum !== prevState.museum || this.state.closures !== prevState.closures
    ) {
      this.scheduleQuote();
    }
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.quoteTimer);
  }

  /** Re-price the request (debounced) whenever the date, group size or type changes. */
  private scheduleQuote(): void {
    clearTimeout(this.quoteTimer);
    const { museum, form } = this.state;
    const participants = Number(form.participants) || 0;
    if (!museum || !form.preferredDate || participants <= this.maxSize() || this.dateProblem(form.preferredDate)) {
      if (this.state.quote || this.state.quoteLoading) this.setState({ quote: null, quoteLoading: false });
      return;
    }
    this.quoteTimer = setTimeout(() => {
      const id = ++this.quoteRequest;
      this.setState({ quoteLoading: true });
      api
        .get<GroupQuote>('/group-requests/quote/', {
          params: { museum: museum.slug, date: form.preferredDate, participants, group_type: form.groupType },
        })
        .then((r) => this.mounted && id === this.quoteRequest && this.setState({ quote: r.data, quoteLoading: false }))
        .catch(() => this.mounted && id === this.quoteRequest && this.setState({ quote: null, quoteLoading: false }));
    }, 350);
  }

  private loadMuseum(): void {
    const slug = this.props.router.params.slug;
    cachedGet<Museum>(`/museums/${slug}/`, undefined, (m) => {
      if (!this.mounted) return;
      this.setState((s) => {
        let date = s.form.preferredDate;
        if (!date) {
          let offset = MIN_LEAD_DAYS;
          while (m.closed_weekday !== null && djangoWeekday(isoDate(offset)) === m.closed_weekday) offset++;
          date = isoDate(offset);
        }
        return { museum: m, form: { ...s.form, preferredDate: date } };
      });
    }).catch((err: unknown) => {
      if (this.mounted) this.setState({ museumError: errorMessage(err, this.props.i18n.t('groups.placeNotFoundText')) });
    });
    cachedGet<PublicClosure[]>(`/museums/${slug}/closures/`, undefined, (closures) => {
      if (this.mounted) this.setState({ closures });
    }).catch(() => undefined);
  }

  /** Whole-day closure (holiday, maintenance …) covering an ISO date. */
  private closureOn(day: string): PublicClosure | undefined {
    return this.state.closures.find((c) => c.all_day && c.start_date <= day && day <= c.end_date);
  }

  private prefill(): void {
    const user = this.props.auth.user;
    if (!user || this.prefilled) return;
    this.prefilled = true;
    this.setState((s) => ({
      form: {
        ...s.form,
        contactName: s.form.contactName || `${user.first_name} ${user.last_name}`.trim(),
        contactEmail: s.form.contactEmail || user.email,
        contactPhone: s.form.contactPhone || user.phone,
      },
    }));
  }

  private loadRequests(): void {
    api
      .get<Paginated<GroupRequest>>('/group-requests/', { params: { mine: 1, page: this.state.page } })
      .then((r) => {
        if (this.mounted) this.setState({ requests: r.data });
      })
      .catch((err) => {
        if (this.mounted) this.setState({ listError: errorMessage(err), requests: { count: 0, next: null, previous: null, results: [] } });
      });
  }

  private set = <K extends keyof FormState>(key: K, value: FormState[K]): void => {
    this.setState((s) => ({ form: { ...s.form, [key]: value } }));
  };

  private onInput = (key: keyof FormState) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>): void => {
    this.set(key, e.target.value as never);
  };

  private maxSize(): number {
    return this.state.museum?.group_policy?.max_size ?? MAX_GROUP_DEFAULT;
  }

  private escortCap(): number {
    const { form, museum } = this.state;
    const n = Number(form.participants) || 0;
    if (!isEducational(form.groupType) || n <= 0) return 0;
    return Math.ceil(n / (museum?.group_policy?.escorts_per ?? 10));
  }

  private dateProblem(day: string): string {
    const { museum } = this.state;
    const { t } = this.props.i18n;
    if (!day) return '';
    if (day < isoDate(MIN_LEAD_DAYS)) return t('groups.err.lead', { n: MIN_LEAD_DAYS });
    if (day > isoDate(WINDOW_DAYS)) return t('groups.err.window', { n: WINDOW_DAYS });
    if (museum && museum.closed_weekday !== null && djangoWeekday(day) === museum.closed_weekday) {
      return t('groups.err.closed', { place: museum.name, day: this.weekday(museum.closed_weekday) });
    }
    const closure = this.closureOn(day);
    if (museum && closure) return t('groups.err.closedDay', { place: museum.name, date: formatDate(day), reason: closure.reason });
    return '';
  }

  /** Weekday name in the current language (WEEKDAYS index: 0 = Monday). */
  private weekday(index: number): string {
    const key = `common.weekday.${index}`;
    const name = this.props.i18n.t(key);
    return name === key ? WEEKDAYS[index] : name;
  }

  private submit = async (e: React.FormEvent<HTMLFormElement>): Promise<void> => {
    e.preventDefault();
    const { museum, form } = this.state;
    if (!museum) return;
    const problem = this.dateProblem(form.preferredDate) || this.dateProblem(form.alternativeDate);
    if (problem) {
      this.setState({ error: problem });
      return;
    }
    const payload: GroupRequestInput = {
      museum: museum.slug,
      preferred_date: form.preferredDate,
      alternative_date: form.alternativeDate || null,
      preferred_time: form.preferredTime,
      group_type: form.groupType,
      organisation_name: form.organisation.trim(),
      contact_name: form.contactName.trim(),
      contact_email: form.contactEmail.trim(),
      contact_phone: form.contactPhone.trim(),
      participants: Number(form.participants),
      escorts: isEducational(form.groupType) ? Number(form.escorts) || 0 : 0,
      needs_guide: form.needsGuide,
      notes: form.notes.trim(),
    };
    this.setState({ submitting: true, error: '' });
    try {
      const { data } = await api.post<GroupRequest>('/group-requests/', payload);
      if (!this.mounted) return;
      this.setState((s) => ({
        created: data,
        submitting: false,
        page: 1,
        form: { ...s.form, participants: '', escorts: '0', notes: '', alternativeDate: '' },
      }));
      this.loadRequests();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      if (this.mounted) this.setState({ submitting: false, error: errorMessage(err) });
    }
  };

  private cancel = async (r: GroupRequest): Promise<void> => {
    if (!window.confirm(this.props.i18n.t('groups.req.confirmCancel', { ref: r.reference, n: r.participants }))) return;
    this.setState({ busyId: r.id, listError: '' });
    try {
      const { data } = await api.post<GroupRequest>(`/group-requests/${r.id}/cancel/`);
      if (!this.mounted) return;
      this.setState((s) => ({
        busyId: null,
        requests: s.requests && { ...s.requests, results: s.requests.results.map((x) => (x.id === r.id ? data : x)) },
      }));
    } catch (err) {
      if (this.mounted) this.setState({ busyId: null, listError: errorMessage(err) });
    }
  };

  private renderProcess(): React.ReactNode {
    const max = this.maxSize();
    const { t } = this.props.i18n;
    return (
      <div className="card border-0 bg-sand mb-4">
        <div className="card-body">
          <h2 className="h5 mb-3"><i className="bi bi-info-circle me-2" aria-hidden="true" />{t('groups.how.title')}</h2>
          <ol className="mb-0 ps-3 small">
            <li className="mb-2">{t('groups.how.step1', { max })}</li>
            <li className="mb-2">{t('groups.how.step2a')}<strong>{t('groups.how.step2b')}</strong>{t('groups.how.step2c')}</li>
            <li className="mb-2">{t('groups.how.step3')}</li>
            <li>{t('groups.how.step4a')}<strong>{t('groups.how.step4b')}</strong>{t('groups.how.step4c')}<strong>{t('groups.how.step4d')}</strong>{t('groups.how.step4e')}</li>
          </ol>
        </div>
      </div>
    );
  }

  private renderForm(museum: Museum): React.ReactNode {
    const { form, submitting, error } = this.state;
    const max = this.maxSize();
    const educational = isEducational(form.groupType);
    const escortCap = this.escortCap();
    const minDate = isoDate(MIN_LEAD_DAYS);
    const maxDate = isoDate(WINDOW_DAYS);
    const prefProblem = this.dateProblem(form.preferredDate);
    const altProblem = this.dateProblem(form.alternativeDate);
    const discount = educational ? museum.school_discount_percent : museum.group_discount_percent;
    const { t } = this.props.i18n;
    return (
      <form className="card border-0 shadow-sm" onSubmit={this.submit}>
        <div className="card-body p-4">
          <h2 className="h4 mb-3">{t('groups.form.yourGroup')}</h2>
          <div className="row g-3">
            <div className="col-md-6">
              <label htmlFor="gr-type" className="form-label">{t('groups.form.type')}</label>
              <select id="gr-type" className="form-select" value={form.groupType} onChange={this.onInput('groupType')}>
                {GROUP_TYPES.map((g) => <option key={g.value} value={g.value}>{t(`common.groupType.${g.value}`)}</option>)}
              </select>
              {discount > 0 && <div className="form-text">{t(educational ? 'groups.form.discountSchools' : 'groups.form.discountGroups', { n: discount })}</div>}
            </div>
            <div className="col-md-6">
              <label htmlFor="gr-org" className="form-label">{educational ? t('groups.form.schoolName') : t('groups.form.orgName')}</label>
              <input id="gr-org" className="form-control" required maxLength={150} value={form.organisation} onChange={this.onInput('organisation')} />
            </div>
            <div className="col-sm-6">
              <label htmlFor="gr-participants" className="form-label">{educational ? t('groups.form.students') : t('groups.form.participants')}</label>
              <input
                id="gr-participants" type="number" className="form-control" required min={max + 1} max={GROUP_REQUEST_MAX}
                value={form.participants} onChange={this.onInput('participants')} placeholder={`${max + 1}–${GROUP_REQUEST_MAX}`}
              />
              <div className="form-text">{t('groups.form.sizeHelp', { max, cap: GROUP_REQUEST_MAX })}</div>
            </div>
            {educational && (
              <div className="col-sm-6">
                <label htmlFor="gr-escorts" className="form-label">{t('groups.form.escorts')}</label>
                <input id="gr-escorts" type="number" className="form-control" min={0} max={escortCap} value={form.escorts} onChange={this.onInput('escorts')} />
                <div className="form-text">{t('groups.form.escortsHelp', { n: escortCap, per: museum.group_policy?.escorts_per ?? 10 })}</div>
              </div>
            )}
          </div>

          <h2 className="h4 mt-4 mb-3">{t('groups.form.when')}</h2>
          <div className="row g-3">
            <div className="col-sm-6 col-lg-4">
              <label htmlFor="gr-date" className="form-label">{t('groups.form.preferredDate')}</label>
              <input id="gr-date" type="date" className={`form-control ${prefProblem ? 'is-invalid' : ''}`} required min={minDate} max={maxDate} value={form.preferredDate} onChange={this.onInput('preferredDate')} />
              {prefProblem && <div className="invalid-feedback">{prefProblem}</div>}
            </div>
            <div className="col-sm-6 col-lg-4">
              <label htmlFor="gr-alt" className="form-label">{t('groups.form.altDate')} <span className="text-muted small">{t('groups.form.optional')}</span></label>
              <input id="gr-alt" type="date" className={`form-control ${altProblem ? 'is-invalid' : ''}`} min={minDate} max={maxDate} value={form.alternativeDate} onChange={this.onInput('alternativeDate')} />
              {altProblem && <div className="invalid-feedback">{altProblem}</div>}
            </div>
            <div className="col-lg-4">
              <label htmlFor="gr-time" className="form-label">{t('groups.form.preferredTime')}</label>
              <select id="gr-time" className="form-select" value={form.preferredTime} onChange={this.onInput('preferredTime')}>
                {PREFERRED_TIMES.map((pt) => <option key={pt.value} value={pt.value}>{t(`groups.time.${pt.value}`)}</option>)}
              </select>
            </div>
          </div>
          {museum.closed_weekday !== null && (
            <p className="text-muted small mt-2 mb-0">
              <i className="bi bi-calendar-event me-1" aria-hidden="true" />
              {t('groups.form.closedOpen', { day: this.weekday(museum.closed_weekday), from: formatTime(museum.opening_time), to: formatTime(museum.closing_time) })}
            </p>
          )}
          {this.renderQuote()}

          <h2 className="h4 mt-4 mb-3">{t('groups.form.contact')}</h2>
          <div className="row g-3">
            <div className="col-md-4">
              <label htmlFor="gr-name" className="form-label">{t('groups.form.name')}</label>
              <input id="gr-name" className="form-control" required maxLength={120} value={form.contactName} onChange={this.onInput('contactName')} />
            </div>
            <div className="col-md-4">
              <label htmlFor="gr-email" className="form-label">{t('account.email')}</label>
              <input id="gr-email" type="email" className="form-control" required value={form.contactEmail} onChange={this.onInput('contactEmail')} />
            </div>
            <div className="col-md-4">
              <label htmlFor="gr-phone" className="form-label">{t('account.mobile')}</label>
              <input id="gr-phone" type="tel" className="form-control" required pattern="\+?[0-9]{10,13}" value={form.contactPhone} onChange={this.onInput('contactPhone')} />
            </div>
          </div>

          <div className="form-check mt-4">
            <input id="gr-guide" type="checkbox" className="form-check-input" checked={form.needsGuide} onChange={(e) => this.set('needsGuide', e.target.checked)} />
            <label htmlFor="gr-guide" className="form-check-label">{t('groups.form.guide')}</label>
          </div>
          <div className="mt-3">
            <label htmlFor="gr-notes" className="form-label">{t('groups.form.notes')} <span className="text-muted small">{t('groups.form.optional')}</span></label>
            <textarea id="gr-notes" className="form-control" rows={3} value={form.notes} onChange={this.onInput('notes')} placeholder={t('groups.form.notesPlaceholder')} />
          </div>

          {error && <div className="alert alert-danger mt-3 mb-0">{error}</div>}
          <button className="btn btn-accent btn-lg mt-4" disabled={submitting}>
            {submitting ? t('booking.sending') : t('groups.form.submit')}
          </button>
        </div>
      </form>
    );
  }

  private renderQuote(): React.ReactNode {
    const { quote, quoteLoading } = this.state;
    const { t } = this.props.i18n;
    if (!quote && !quoteLoading) return null;
    if (!quote) {
      return (
        <p className="small text-muted mt-3 mb-0" aria-live="polite">
          <span className="spinner-border spinner-border-sm me-2" aria-hidden="true" />
          {t('groups.quote.loading')}
        </p>
      );
    }
    if (quote.closed) {
      const museum = this.state.museum;
      return (
        <div className="alert alert-warning small mt-3 mb-0" role="alert">
          <i className="bi bi-exclamation-triangle me-2" aria-hidden="true" />
          {quote.closed_weekly || !museum
            ? quote.closed
            : t('groups.err.closedDay', { place: museum.name, date: formatDate(quote.date), reason: quote.closed_reason })}
        </div>
      );
    }
    if (!quote.ticket_type) return null;
    const discount = Number(quote.discount);
    return (
      <div className={`border rounded-3 p-3 mt-3 bg-light ${quoteLoading ? 'opacity-50' : ''}`} aria-live="polite">
        <div className="d-flex flex-wrap justify-content-between align-items-baseline gap-2">
          <h3 className="h6 mb-0">
            <i className="bi bi-calculator me-2 text-accent" aria-hidden="true" />
            {t('groups.quote.title', { date: formatDate(quote.date, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }) })}
          </h3>
          <strong className="fs-5">{formatINR(quote.total)}</strong>
        </div>
        <ul className="list-unstyled small mb-0 mt-2">
          <li>{t('groups.quote.line', { n: quote.participants, ticket: quote.ticket_type.name, price: formatINR(quote.unit_price), amount: formatINR(quote.subtotal) })}</li>
          {quote.price_rule && (
            <li className="text-muted">
              <i className="bi bi-tag me-1" aria-hidden="true" />
              {t('groups.quote.rule', { rule: quote.price_rule, base: formatINR(quote.base_unit_price) })}
            </li>
          )}
          {discount > 0 && <li>{t('groups.quote.discount', { n: quote.discount_percent, amount: formatINR(discount) })}</li>}
        </ul>
        <p className="small text-muted mb-0 mt-2">{t('groups.quote.note')}</p>
      </div>
    );
  }

  private renderRequest(r: GroupRequest): React.ReactNode {
    const st = groupRequestStatus(r.status);
    const { busyId } = this.state;
    const { t } = this.props.i18n;
    const statusKey = `groups.status.${r.status}`;
    const statusLabel = t(statusKey) === statusKey ? st.label : t(statusKey);
    const showBookings = r.bookings.length > 0 && ['approved', 'paid', 'expired'].includes(r.status);
    return (
      <div key={r.id} className="card border-0 shadow-sm mb-3">
        <div className="card-body">
          <div className="d-flex justify-content-between flex-wrap gap-2">
            <div>
              <div className="small text-muted"><span className="ref">{r.reference}</span> · {t('groups.req.sent', { when: formatDateTime(r.created_at) })}</div>
              <h3 className="h5 mb-1">
                <Link to={`/museums/${r.museum_slug}`} className="text-reset">{r.museum_name}</Link>
                <span className="text-muted fw-normal">, {r.city_name}</span>
              </h3>
              <div className="small">
                <i className="bi bi-people me-1" aria-hidden="true" />
                {r.organisation_name} · {r.participants} {r.escorts > 0 && t('groups.req.plusEscorts', { n: r.escorts })} · {t(`common.groupType.${r.group_type}`)}
              </div>
              <div className="small text-muted">
                <i className="bi bi-calendar-event me-1" aria-hidden="true" />
                {formatDate(r.preferred_date, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}
                {r.alternative_date && ` ${t('groups.req.orDate', { date: formatDate(r.alternative_date) })}`} · {t(`groups.time.${r.preferred_time}`)}
              </div>
            </div>
            <div className="text-end">
              <span className={`badge ${st.bg}`}>{statusLabel}</span>
              {r.can_cancel && (
                <div className="mt-2">
                  <button type="button" className="btn btn-sm btn-outline-danger" disabled={busyId === r.id} onClick={() => this.cancel(r)}>
                    {busyId === r.id ? t('groups.req.cancelling') : t('groups.req.cancel')}
                  </button>
                </div>
              )}
            </div>
          </div>

          {(r.status === 'submitted' || r.status === 'under_review') && (
            <p className="small text-muted mt-3 mb-0">
              <i className="bi bi-hourglass-split me-1" aria-hidden="true" />
              {r.status === 'submitted' ? t('groups.req.waiting') : t('groups.req.planning')} {t('groups.req.replyWithin')}
            </p>
          )}
          {r.status === 'declined' && r.staff_notes && (
            <div className="alert alert-light border small mt-3 mb-0"><strong>{t('groups.req.reason')}:</strong> {r.staff_notes}</div>
          )}

          {showBookings && (
            <div className="mt-3">
              <div className="row g-2 mb-2 small">
                {r.approved_date && <div className="col-sm-6 col-lg-3"><div className="fact"><span className="label">{t('groups.req.visitDate')}</span>{formatDate(r.approved_date)}</div></div>}
                {r.quoted_total !== null && <div className="col-sm-6 col-lg-3"><div className="fact"><span className="label">{t('booking.total')}{r.discount_percent ? ` ${t('groups.req.percentOff', { n: r.discount_percent })}` : ''}</span><strong>{formatINR(r.quoted_total)}</strong></div></div>}
                {r.payment_mode && <div className="col-sm-6 col-lg-3"><div className="fact"><span className="label">{t('groups.req.payment')}</span>{t(`groups.payMode.${r.payment_mode}`)}</div></div>}
                {r.pay_by && r.status === 'approved' && <div className="col-sm-6 col-lg-3"><div className="fact"><span className="label">{t('groups.req.payBy')}</span><strong className="text-accent">{formatDateTime(r.pay_by)}</strong></div></div>}
              </div>
              {r.status === 'approved' && r.payment_mode === 'invoice' && (
                <p className="small text-muted mb-2">
                  <i className="bi bi-bank me-1" aria-hidden="true" />
                  {t('groups.req.invoiceNote', { email: r.contact_email })}
                </p>
              )}
              {r.status === 'approved' && r.payment_mode === 'online' && (
                <p className="small text-muted mb-2">
                  <i className="bi bi-credit-card me-1" aria-hidden="true" />
                  {t('groups.req.onlineNote')}
                </p>
              )}
              <div className="table-responsive">
                <table className="table table-sm align-middle mb-0">
                  <thead className="table-light">
                    <tr><th>{t('groups.req.colBooking')}</th><th>{t('groups.req.colSlot')}</th><th className="text-end">{t('groups.req.colPeople')}</th><th className="text-end">{t('groups.req.colAmount')}</th><th>{t('groups.req.colStatus')}</th><th /></tr>
                  </thead>
                  <tbody>
                    {r.bookings.map((b) => (
                      <tr key={b.reference}>
                        <td className="ref">{b.reference}</td>
                        <td>{formatTime(b.slot_start)} – {formatTime(b.slot_end)}</td>
                        <td className="text-end">{b.total_visitors}</td>
                        <td className="text-end">{formatINR(b.total_amount)}</td>
                        <td><StatusBadge status={b.status} /></td>
                        <td className="text-end">
                          {b.status === 'pending' && r.payment_mode === 'online' ? (
                            <Link to={`/checkout/${b.reference}`} className="btn btn-sm btn-accent">{t('groups.req.payNow')}</Link>
                          ) : b.status === 'confirmed' || b.status === 'checked_in' ? (
                            <Link to={`/tickets/${b.reference}`} className="btn btn-sm btn-outline-primary">{t('groups.req.ticket')}</Link>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  public render(): React.ReactNode {
    const { auth, router } = this.props;
    const { museum, museumError, created, requests, page, listError } = this.state;
    const { t } = this.props.i18n;
    if (auth.loading) return <Loader />;
    if (!auth.user) return <Navigate to="/login" state={{ from: router.location.pathname }} replace />;
    if (museumError) return <div className="container page py-5"><Empty title={t('groups.placeNotFound')}>{museumError}</Empty></div>;
    if (!museum) return <Loader />;

    return (
      <div className="container page py-4 py-lg-5">
        <Link to={`/museums/${museum.slug}`} className="btn btn-link px-0 mb-2 text-decoration-none">
          <i className="bi bi-arrow-left me-1" aria-hidden="true" /> {t('groups.backTo', { place: museum.name })}
        </Link>
        <h1 className="display-6 mb-1">{t('groups.title')}</h1>
        <p className="text-muted mb-4">{museum.name}, {museum.city_name}</p>

        {created && (
          <div className="alert alert-success d-flex gap-3 align-items-start">
            <i className="bi bi-check-circle fs-4" aria-hidden="true" />
            <div>
              <strong>{t('groups.created.title', { ref: created.reference })}</strong> {t('groups.created.text', { email: created.contact_email })}
            </div>
          </div>
        )}

        {museum.group_requests_open === false || !museum.allow_groups ? (
          <div className="alert alert-warning">{museum.allow_groups && museum.groups_paused_message ? museum.groups_paused_message : t('groups.noGroups', { place: museum.name })}</div>
        ) : (
          <div className="row g-4">
            <div className="col-lg-8">{this.renderForm(museum)}</div>
            <div className="col-lg-4">{this.renderProcess()}</div>
          </div>
        )}

        <h2 className="h3 mt-5 mb-3">{t('groups.yourRequests')}</h2>
        {listError && <div className="alert alert-danger">{listError}</div>}
        {requests === null ? (
          <Loader />
        ) : requests.count === 0 ? (
          <p className="text-muted">{t('groups.noRequests')}</p>
        ) : (
          <>
            {requests.results.map((r) => this.renderRequest(r))}
            <Pagination page={page} count={requests.count} onChange={(p) => this.setState({ page: p })} />
          </>
        )}
      </div>
    );
  }
}

export default withRouter(withAuth(withI18n(GroupRequestPage)));
