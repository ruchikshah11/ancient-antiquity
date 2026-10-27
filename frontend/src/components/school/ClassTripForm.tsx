import * as React from 'react';
import { api, errorMessage } from '../../api/client';
import {
  createTrip,
  estimateTrip,
  MAX_STUDENTS,
  MIN_STUDENTS,
  STUDENTS_PER_TEACHER,
  teachersNeeded,
  WINDOW_DAYS,
} from '../../api/schools';
import type {
  GuideLanguage,
  MuseumSummary,
  Paginated,
  SchoolEstimate,
  SchoolTrip,
  SchoolTripInput,
  SlotPreference,
} from '../../api/types';
import { withI18n, WithI18nProps } from '../../i18n';
import { djangoWeekday, formatINR, isoDate, WEEKDAYS } from '../../utils/format';
import { placeLocation } from '../../utils/format';

interface ClassTripFormProps extends WithI18nProps {
  onCreated: (trip: SchoolTrip) => void;
}

interface TripFormFields {
  preferredDate: string;
  alternativeDate: string;
  slot: SlotPreference;
  grades: string;
  students: string;
  young: string;
  teachers: string;
  helpers: string;
  access: string;
  guide: GuideLanguage;
  notes: string;
}

interface ClassTripFormState {
  place: MuseumSummary | null;
  search: string;
  results: MuseumSummary[];
  searching: boolean;
  form: TripFormFields;
  estimate: SchoolEstimate | null;
  estimating: boolean;
  submitting: boolean;
  error: string;
}

const EMPTY: TripFormFields = {
  preferredDate: '', alternativeDate: '', slot: 'morning', grades: '', students: '', young: '0', teachers: '',
  helpers: '0', access: '', guide: '', notes: '',
};

const SLOTS: SlotPreference[] = ['morning', 'afternoon'];
const GUIDES: GuideLanguage[] = ['', 'hi', 'en'];

/** "Plan a class trip": place search, dates, class size and a live price estimate. */
class ClassTripFormBase extends React.Component<ClassTripFormProps, ClassTripFormState> {
  public state: ClassTripFormState = {
    place: null, search: '', results: [], searching: false, form: { ...EMPTY }, estimate: null, estimating: false,
    submitting: false, error: '',
  };

  private mounted = false;
  private searchTimer: ReturnType<typeof setTimeout> | undefined;
  private estimateTimer: ReturnType<typeof setTimeout> | undefined;
  private estimateSeq = 0;

  public componentDidMount(): void {
    this.mounted = true;
  }

  public componentDidUpdate(_prev: ClassTripFormProps, prev: ClassTripFormState): void {
    if (prev.search !== this.state.search) this.scheduleSearch();
    const f = this.state.form;
    const p = prev.form;
    if (
      prev.place !== this.state.place || f.preferredDate !== p.preferredDate || f.students !== p.students
      || f.young !== p.young || f.teachers !== p.teachers || f.helpers !== p.helpers
    ) {
      this.scheduleEstimate();
    }
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.searchTimer);
    clearTimeout(this.estimateTimer);
  }

  private scheduleSearch(): void {
    clearTimeout(this.searchTimer);
    const q = this.state.search.trim();
    if (q.length < 2) {
      this.setState({ results: [], searching: false });
      return;
    }
    this.searchTimer = setTimeout(() => {
      this.setState({ searching: true });
      api
        .get<Paginated<MuseumSummary>>('/museums/', { params: { search: q } })
        .then((r) => this.mounted && this.setState({ results: r.data.results.slice(0, 8), searching: false }))
        .catch(() => this.mounted && this.setState({ results: [], searching: false }));
    }, 300);
  }

  private scheduleEstimate(): void {
    clearTimeout(this.estimateTimer);
    const { place, form } = this.state;
    const students = Number(form.students) || 0;
    if (!place || students < 1) {
      this.setState({ estimate: null, estimating: false });
      return;
    }
    this.estimateTimer = setTimeout(() => {
      const seq = ++this.estimateSeq;
      this.setState({ estimating: true });
      estimateTrip({
        museum: place.slug,
        date: form.preferredDate || undefined,
        students: Math.min(students, MAX_STUDENTS),
        young_students: Math.min(Number(form.young) || 0, students),
        teachers: Number(form.teachers) || 0,
        helpers: Number(form.helpers) || 0,
      })
        .then((est) => this.mounted && seq === this.estimateSeq && this.setState({ estimate: est, estimating: false }))
        .catch(() => this.mounted && seq === this.estimateSeq && this.setState({ estimate: null, estimating: false }));
    }, 400);
  }

  private choosePlace = (m: MuseumSummary): void => {
    this.setState((s) => {
      let date = s.form.preferredDate;
      if (!date || (m.closed_weekday !== null && djangoWeekday(date) === m.closed_weekday)) {
        let offset = 7;
        while (m.closed_weekday !== null && djangoWeekday(isoDate(offset)) === m.closed_weekday) offset++;
        date = isoDate(offset);
      }
      return { place: m, search: '', results: [], form: { ...s.form, preferredDate: date } };
    });
  };

  private set = <K extends keyof TripFormFields>(key: K, value: TripFormFields[K]): void => {
    this.setState((s) => ({ form: { ...s.form, [key]: value } }));
  };

  private onInput = (key: keyof TripFormFields) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>): void => {
    this.set(key, e.target.value as never);
  };

  private weekday(index: number): string {
    const key = `common.weekday.${index}`;
    const name = this.props.i18n.t(key);
    return name === key ? WEEKDAYS[index] : name;
  }

  private dateProblem(day: string): string {
    const { place } = this.state;
    const { t } = this.props.i18n;
    if (!day) return '';
    if (day <= isoDate(0)) return t('schools.err.past');
    if (day > isoDate(WINDOW_DAYS)) return t('schools.err.window', { n: WINDOW_DAYS });
    if (place && place.closed_weekday !== null && djangoWeekday(day) === place.closed_weekday) {
      return t('schools.err.closed', { place: place.name, day: this.weekday(place.closed_weekday) });
    }
    return '';
  }

  private problem(): string {
    const { place, form } = this.state;
    const { t } = this.props.i18n;
    if (!place) return t('schools.err.choosePlace');
    const dateProblem = this.dateProblem(form.preferredDate) || this.dateProblem(form.alternativeDate);
    if (dateProblem) return dateProblem;
    if (form.alternativeDate && form.alternativeDate === form.preferredDate) return t('schools.err.sameDate');
    const students = Number(form.students) || 0;
    if (students < MIN_STUDENTS) return t('schools.err.minStudents', { n: MIN_STUDENTS });
    if ((Number(form.young) || 0) > students) return t('schools.err.young');
    if ((Number(form.teachers) || 0) < teachersNeeded(students)) {
      return t('schools.err.ratio', { per: STUDENTS_PER_TEACHER, n: teachersNeeded(students) });
    }
    return '';
  }

  private submit = async (e: React.FormEvent<HTMLFormElement>): Promise<void> => {
    e.preventDefault();
    const problem = this.problem();
    if (problem) {
      this.setState({ error: problem });
      return;
    }
    const { place, form } = this.state;
    const payload: SchoolTripInput = {
      museum: place!.slug,
      preferred_date: form.preferredDate,
      alternative_date: form.alternativeDate || null,
      slot_preference: form.slot,
      grades: form.grades.trim(),
      students: Number(form.students),
      young_students: this.hasChildTicket() ? Number(form.young) || 0 : 0,
      teachers: Number(form.teachers),
      helpers: Number(form.helpers) || 0,
      accessibility_needs: form.access.trim(),
      guide_language: form.guide,
      notes: form.notes.trim(),
    };
    this.setState({ submitting: true, error: '' });
    try {
      const trip = await createTrip(payload);
      if (!this.mounted) return;
      this.setState({ submitting: false, form: { ...EMPTY }, place: null, estimate: null });
      this.props.onCreated(trip);
    } catch (err) {
      if (this.mounted) this.setState({ submitting: false, error: errorMessage(err) });
    }
  };

  private hasChildTicket(): boolean {
    const est = this.state.estimate;
    return !!est?.child_ticket && est.child_ticket.id !== est.student_ticket?.id;
  }

  private renderPlace(): React.ReactNode {
    const { place, search, results, searching } = this.state;
    const { t } = this.props.i18n;
    if (place) {
      return (
        <div className="d-flex justify-content-between align-items-center border rounded p-2 ps-3 bg-light">
          <div>
            <strong>{place.name}</strong>
            <div className="small text-muted">
              {placeLocation(place.city_name, place.state_name)}
              {place.closed_weekday !== null && ` · ${t('schools.trip.closedOn', { day: this.weekday(place.closed_weekday) })}`}
            </div>
          </div>
          <button type="button" className="btn btn-sm btn-light" onClick={() => this.setState({ place: null })}>{t('schools.trip.change')}</button>
        </div>
      );
    }
    return (
      <div className="position-relative">
        <input
          id="st-place" className="form-control" autoComplete="off" value={search} placeholder={t('schools.trip.placeSearch')}
          onChange={(e) => this.setState({ search: e.target.value })}
        />
        {search.trim().length >= 2 && !searching && (
          <div className="list-group school-place-results shadow-sm mt-1">
            {results.length === 0 && <div className="list-group-item small text-muted">{t('schools.trip.noPlaces')}</div>}
            {results.map((m) => (
              <button key={m.id} type="button" className="list-group-item list-group-item-action" onClick={() => this.choosePlace(m)}>
                <span className="fw-semibold">{m.name}</span> <span className="small text-muted">{placeLocation(m.city_name, m.state_name)}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  private renderEstimate(): React.ReactNode {
    const { estimate, estimating, place, form } = this.state;
    const { t } = this.props.i18n;
    const ready = place && (Number(form.students) || 0) > 0;
    return (
      <div className="card border-0 school-estimate">
        <div className="card-body">
          <h3 className="h5 mb-3"><i className="bi bi-calculator me-2" aria-hidden="true" />{t('schools.est.title')}</h3>
          {!ready || !estimate ? (
            <p className="small text-muted mb-0">{ready && estimating ? t('schools.est.loading') : t('schools.est.empty')}</p>
          ) : (
            <>
              <table className="table table-sm small mb-2">
                <tbody>
                  {estimate.lines.map((l) => (
                    <tr key={`${l.kind}-${l.name}`}>
                      <td>
                        {t(`schools.kind.${l.kind}`)}
                        <div className="text-muted">{l.quantity} × {l.name} ({Number(l.unit_price) === 0 ? t('schools.est.free') : formatINR(l.unit_price)})</div>
                      </td>
                      <td className="text-end align-middle">{Number(l.amount) === 0 ? t('schools.est.free') : formatINR(l.amount)}</td>
                    </tr>
                  ))}
                  {estimate.free_teachers > 0 && (
                    <tr>
                      <td><i className="bi bi-person-check me-1 text-success" aria-hidden="true" />{t('schools.est.freeTeachers', { n: estimate.free_teachers })}</td>
                      <td className="text-end text-success">{t('schools.est.free')}</td>
                    </tr>
                  )}
                  {Number(estimate.discount) > 0 && (
                    <tr>
                      <td>{t('schools.est.discount', { n: estimate.discount_percent })}</td>
                      <td className="text-end text-success">− {formatINR(estimate.discount)}</td>
                    </tr>
                  )}
                </tbody>
              </table>
              <div className="d-flex justify-content-between align-items-baseline">
                <span>{t('schools.est.total')}</span>
                <strong className="fs-4 text-accent">{Number(estimate.total) === 0 ? t('schools.est.free') : formatINR(estimate.total)}</strong>
              </div>
              <div className="small text-muted">{t('schools.est.people', { n: estimate.people })}</div>
              {estimate.date_error && <div className="small text-danger mt-1">{estimate.date_error}</div>}
              <p className="small text-muted mt-2 mb-0">{t('schools.est.note')}</p>
            </>
          )}
        </div>
      </div>
    );
  }

  public render(): React.ReactNode {
    const { form, submitting, error, estimate } = this.state;
    const { t } = this.props.i18n;
    const students = Number(form.students) || 0;
    const needed = teachersNeeded(students);
    const prefProblem = this.dateProblem(form.preferredDate);
    const altProblem = this.dateProblem(form.alternativeDate);
    const childTicket = this.hasChildTicket() ? estimate!.child_ticket : null;
    return (
      <form className="row g-4" onSubmit={this.submit} id="plan-trip">
        <div className="col-lg-8">
          <div className="card border-0 shadow-sm">
            <div className="card-body p-4">
              <h2 className="h4 mb-3"><i className="bi bi-calendar-event me-2 text-primary" aria-hidden="true" />{t('schools.trip.title')}</h2>
              <label htmlFor="st-place" className="form-label">{t('schools.trip.place')}</label>
              {this.renderPlace()}

              <div className="row g-3 mt-1">
                <div className="col-sm-6 col-lg-4">
                  <label htmlFor="st-date" className="form-label">{t('schools.trip.preferredDate')}</label>
                  <input id="st-date" type="date" className={`form-control ${prefProblem ? 'is-invalid' : ''}`} required min={isoDate(1)} max={isoDate(WINDOW_DAYS)} value={form.preferredDate} onChange={this.onInput('preferredDate')} />
                  {prefProblem && <div className="invalid-feedback">{prefProblem}</div>}
                </div>
                <div className="col-sm-6 col-lg-4">
                  <label htmlFor="st-alt" className="form-label">{t('schools.trip.altDate')} <span className="text-muted small">{t('schools.reg.optional')}</span></label>
                  <input id="st-alt" type="date" className={`form-control ${altProblem ? 'is-invalid' : ''}`} min={isoDate(1)} max={isoDate(WINDOW_DAYS)} value={form.alternativeDate} onChange={this.onInput('alternativeDate')} />
                  {altProblem && <div className="invalid-feedback">{altProblem}</div>}
                </div>
                <div className="col-lg-4">
                  <label htmlFor="st-slot" className="form-label">{t('schools.trip.slot')}</label>
                  <select id="st-slot" className="form-select" value={form.slot} onChange={this.onInput('slot')}>
                    {SLOTS.map((s) => <option key={s} value={s}>{t(`schools.slot.${s}`)}</option>)}
                  </select>
                </div>
              </div>

              <div className="row g-3 mt-1">
                <div className="col-sm-6 col-lg-4">
                  <label htmlFor="st-grades" className="form-label">{t('schools.trip.grades')}</label>
                  <input id="st-grades" className="form-control" required maxLength={60} placeholder={t('schools.trip.gradesPlaceholder')} value={form.grades} onChange={this.onInput('grades')} />
                </div>
                <div className="col-sm-6 col-lg-4">
                  <label htmlFor="st-students" className="form-label">{t('schools.trip.students')}</label>
                  <input id="st-students" type="number" className="form-control" required min={MIN_STUDENTS} max={MAX_STUDENTS} value={form.students} onChange={this.onInput('students')} />
                  <div className="form-text">{t('schools.trip.studentsHelp', { min: MIN_STUDENTS })}</div>
                </div>
                {childTicket && (
                  <div className="col-sm-6 col-lg-4">
                    <label htmlFor="st-young" className="form-label">{t('schools.trip.young', { ticket: childTicket.name })}</label>
                    <input id="st-young" type="number" className="form-control" min={0} max={students || undefined} value={form.young} onChange={this.onInput('young')} />
                    <div className="form-text">{t('schools.trip.youngHelp')}</div>
                  </div>
                )}
                <div className="col-sm-6 col-lg-4">
                  <label htmlFor="st-teachers" className="form-label">{t('schools.trip.teachers')}</label>
                  <input id="st-teachers" type="number" className={`form-control ${form.teachers !== '' && Number(form.teachers) < needed ? 'is-invalid' : ''}`} required min={Math.max(needed, 1)} max={100} value={form.teachers} onChange={this.onInput('teachers')} />
                  <div className="form-text">{t('schools.trip.teachersHelp', { per: STUDENTS_PER_TEACHER, n: Math.max(needed, 1) })}</div>
                </div>
                <div className="col-sm-6 col-lg-4">
                  <label htmlFor="st-helpers" className="form-label">{t('schools.trip.helpers')}</label>
                  <input id="st-helpers" type="number" className="form-control" min={0} max={100} value={form.helpers} onChange={this.onInput('helpers')} />
                </div>
              </div>

              <div className="row g-3 mt-1">
                <div className="col-md-6">
                  <label htmlFor="st-guide" className="form-label"><i className="bi bi-translate me-1" aria-hidden="true" />{t('schools.trip.guide')}</label>
                  <select id="st-guide" className="form-select" value={form.guide} onChange={this.onInput('guide')}>
                    {GUIDES.map((g) => <option key={g || 'none'} value={g}>{t(`schools.guide.${g || 'none'}`)}</option>)}
                  </select>
                </div>
                <div className="col-md-6">
                  <label htmlFor="st-access" className="form-label">{t('schools.trip.access')} <span className="text-muted small">{t('schools.reg.optional')}</span></label>
                  <input id="st-access" className="form-control" maxLength={500} placeholder={t('schools.trip.accessPlaceholder')} value={form.access} onChange={this.onInput('access')} />
                </div>
                <div className="col-12">
                  <label htmlFor="st-notes" className="form-label">{t('schools.trip.notes')} <span className="text-muted small">{t('schools.reg.optional')}</span></label>
                  <textarea id="st-notes" className="form-control" rows={2} value={form.notes} onChange={this.onInput('notes')} />
                </div>
              </div>

              {error && <div className="alert alert-danger mt-3 mb-0">{error}</div>}
              <button className="btn btn-accent btn-lg mt-4" disabled={submitting}>
                {submitting ? t('schools.trip.sending') : t('schools.trip.submit')}
              </button>
            </div>
          </div>
        </div>
        <div className="col-lg-4">
          <div className="school-estimate-sticky">{this.renderEstimate()}</div>
        </div>
      </form>
    );
  }
}

export default withI18n(ClassTripFormBase);
