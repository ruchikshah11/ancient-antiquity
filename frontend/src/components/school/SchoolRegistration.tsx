import * as React from 'react';
import { errorMessage } from '../../api/client';
import { registerSchool, SCHOOL_BOARDS, SCHOOL_STATUS_BG, updateSchool } from '../../api/schools';
import type { School, SchoolBoard, SchoolInput, State, User } from '../../api/types';
import { withI18n, WithI18nProps } from '../../i18n';
import { formatDate } from '../../utils/format';

// ---------------------------------------------------------------- registration / edit form

interface SchoolFormProps extends WithI18nProps {
  user: User;
  states: State[];
  /** The school being edited (null: register a new one). */
  school: School | null;
  onSaved: (school: School) => void;
  onCancel?: () => void;
}

interface SchoolFormState {
  form: SchoolInput;
  saving: boolean;
  error: string;
}

const CONTACT_FIELDS: (keyof SchoolInput)[] = ['contact_name', 'contact_phone', 'contact_email', 'principal_name', 'phone'];

class SchoolFormBase extends React.Component<SchoolFormProps, SchoolFormState> {
  constructor(props: SchoolFormProps) {
    super(props);
    const { school, user } = props;
    this.state = {
      form: school
        ? {
            name: school.name, board: school.board, udise_code: school.udise_code, address: school.address,
            city: school.city, state: school.state, principal_name: school.principal_name, phone: school.phone,
            contact_name: school.contact_name, contact_phone: school.contact_phone, contact_email: school.contact_email,
          }
        : {
            name: '', board: 'cbse', udise_code: '', address: '', city: '', state: 0, principal_name: '', phone: '',
            contact_name: `${user.first_name} ${user.last_name}`.trim(), contact_phone: user.phone, contact_email: user.email,
          },
      saving: false,
      error: '',
    };
  }

  private onInput = (key: keyof SchoolInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>): void => {
    const value = key === 'state' ? Number(e.target.value) : e.target.value;
    this.setState((s) => ({ form: { ...s.form, [key]: value } }));
  };

  private locked(key: keyof SchoolInput): boolean {
    return this.props.school?.status === 'verified' && !CONTACT_FIELDS.includes(key);
  }

  private submit = async (e: React.FormEvent<HTMLFormElement>): Promise<void> => {
    e.preventDefault();
    const { form } = this.state;
    const { t } = this.props.i18n;
    if (form.udise_code && !/^\d{11}$/.test(form.udise_code)) {
      this.setState({ error: t('schools.reg.udiseInvalid') });
      return;
    }
    const clean = Object.fromEntries(
      Object.entries(form).map(([k, v]) => [k, typeof v === 'string' ? v.trim() : v]),
    ) as unknown as SchoolInput;
    this.setState({ saving: true, error: '' });
    try {
      let saved: School;
      if (this.props.school) {
        const body: Partial<SchoolInput> = this.props.school.status === 'verified'
          ? Object.fromEntries(CONTACT_FIELDS.map((k) => [k, clean[k]]))
          : clean;
        saved = await updateSchool(body);
      } else {
        saved = await registerSchool(clean);
      }
      this.setState({ saving: false });
      this.props.onSaved(saved);
    } catch (err) {
      this.setState({ saving: false, error: errorMessage(err) });
    }
  };

  public render(): React.ReactNode {
    const { states, school, onCancel } = this.props;
    const { form, saving, error } = this.state;
    const { t } = this.props.i18n;
    const udiseBad = form.udise_code !== '' && !/^\d{11}$/.test(form.udise_code);
    return (
      <form className="card border-0 shadow-sm" onSubmit={this.submit}>
        <div className="card-body p-4">
          <h2 className="h4 mb-1"><i className="bi bi-building me-2 text-primary" aria-hidden="true" />{school ? t('schools.reg.editTitle') : t('schools.reg.title')}</h2>
          <p className="text-muted small mb-3">{t('schools.reg.intro')}</p>
          {school?.status === 'verified' && <div className="alert alert-info small py-2">{t('schools.reg.verifiedNote')}</div>}
          <div className="row g-3">
            <div className="col-md-8">
              <label htmlFor="sc-name" className="form-label">{t('schools.reg.name')}</label>
              <input id="sc-name" className="form-control" required maxLength={150} disabled={this.locked('name')} value={form.name} onChange={this.onInput('name')} />
            </div>
            <div className="col-md-4">
              <label htmlFor="sc-board" className="form-label">{t('schools.reg.board')}</label>
              <select id="sc-board" className="form-select" disabled={this.locked('board')} value={form.board} onChange={this.onInput('board')}>
                {SCHOOL_BOARDS.map((b: SchoolBoard) => <option key={b} value={b}>{t(`schools.board.${b}`)}</option>)}
              </select>
            </div>
            <div className="col-md-4">
              <label htmlFor="sc-udise" className="form-label">{t('schools.reg.udise')} <span className="text-muted small">{t('schools.reg.optional')}</span></label>
              <input
                id="sc-udise" className={`form-control ${udiseBad ? 'is-invalid' : ''}`} inputMode="numeric" maxLength={11}
                disabled={this.locked('udise_code')} value={form.udise_code} onChange={this.onInput('udise_code')}
              />
              {udiseBad ? <div className="invalid-feedback">{t('schools.reg.udiseInvalid')}</div> : <div className="form-text">{t('schools.reg.udiseHelp')}</div>}
            </div>
            <div className="col-md-8">
              <label htmlFor="sc-address" className="form-label">{t('schools.reg.address')}</label>
              <input id="sc-address" className="form-control" required maxLength={255} disabled={this.locked('address')} value={form.address} onChange={this.onInput('address')} />
            </div>
            <div className="col-md-6">
              <label htmlFor="sc-city" className="form-label">{t('schools.reg.city')}</label>
              <input id="sc-city" className="form-control" required maxLength={80} disabled={this.locked('city')} value={form.city} onChange={this.onInput('city')} />
            </div>
            <div className="col-md-6">
              <label htmlFor="sc-state" className="form-label">{t('schools.reg.state')}</label>
              <select id="sc-state" className="form-select" required disabled={this.locked('state')} value={form.state || ''} onChange={this.onInput('state')}>
                <option value="">{t('schools.reg.chooseState')}</option>
                {states.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
            <div className="col-md-6">
              <label htmlFor="sc-principal" className="form-label">{t('schools.reg.principal')}</label>
              <input id="sc-principal" className="form-control" required maxLength={120} value={form.principal_name} onChange={this.onInput('principal_name')} />
            </div>
            <div className="col-md-6">
              <label htmlFor="sc-phone" className="form-label">{t('schools.reg.phone')}</label>
              <input id="sc-phone" type="tel" className="form-control" required pattern="\+?[0-9]{10,13}" value={form.phone} onChange={this.onInput('phone')} />
            </div>
          </div>

          <h3 className="h5 mt-4 mb-3">{t('schools.reg.contact')}</h3>
          <div className="row g-3">
            <div className="col-md-4">
              <label htmlFor="sc-cname" className="form-label">{t('schools.reg.contactName')}</label>
              <input id="sc-cname" className="form-control" required maxLength={120} value={form.contact_name} onChange={this.onInput('contact_name')} />
            </div>
            <div className="col-md-4">
              <label htmlFor="sc-cphone" className="form-label">{t('schools.reg.contactPhone')}</label>
              <input id="sc-cphone" type="tel" className="form-control" required pattern="\+?[0-9]{10,13}" value={form.contact_phone} onChange={this.onInput('contact_phone')} />
            </div>
            <div className="col-md-4">
              <label htmlFor="sc-cemail" className="form-label">{t('schools.reg.contactEmail')}</label>
              <input id="sc-cemail" type="email" className="form-control" required value={form.contact_email} onChange={this.onInput('contact_email')} />
            </div>
          </div>

          {error && <div className="alert alert-danger mt-3 mb-0">{error}</div>}
          <div className="d-flex gap-2 mt-4">
            <button className="btn btn-accent" disabled={saving}>
              {saving ? t('schools.reg.saving') : !school ? t('schools.reg.submit') : school.status === 'rejected' ? t('schools.reg.resubmit') : t('schools.reg.save')}
            </button>
            {onCancel && <button type="button" className="btn btn-light" onClick={onCancel}>{t('schools.reg.cancel')}</button>}
          </div>
        </div>
      </form>
    );
  }
}

export const SchoolForm = withI18n(SchoolFormBase);

// ---------------------------------------------------------------- school card with its status

interface SchoolCardProps extends WithI18nProps {
  school: School;
  onEdit: () => void;
}

class SchoolCardBase extends React.Component<SchoolCardProps> {
  public render(): React.ReactNode {
    const { school, onEdit } = this.props;
    const { t } = this.props.i18n;
    return (
      <div className="card border-0 shadow-sm school-card">
        <div className="card-body p-4">
          <div className="d-flex justify-content-between align-items-start gap-2 flex-wrap">
            <div>
              <div className="small text-muted text-uppercase">{t('schools.card.title')}</div>
              <h2 className="h4 mb-1">{school.name}</h2>
              <div className="text-muted small">
                <i className="bi bi-geo-alt me-1" aria-hidden="true" />{school.address}, {school.city}, {school.state_name}
              </div>
            </div>
            <div className="text-end">
              <span className={`badge ${SCHOOL_STATUS_BG[school.status]}`}>
                <i className={`bi ${school.status === 'verified' ? 'bi-patch-check' : school.status === 'rejected' ? 'bi-x-octagon' : 'bi-hourglass-split'} me-1`} aria-hidden="true" />
                {t(`schools.status.${school.status}`)}
              </span>
              <div className="mt-2">
                <button type="button" className="btn btn-sm btn-outline-primary" onClick={onEdit}>
                  <i className="bi bi-pencil me-1" aria-hidden="true" />{t('schools.card.edit')}
                </button>
              </div>
            </div>
          </div>
          <div className="row g-2 mt-2 small">
            <div className="col-sm-6 col-lg-3"><div className="fact"><span className="label">{t('schools.reg.board')}</span>{t(`schools.board.${school.board}`)}</div></div>
            <div className="col-sm-6 col-lg-3"><div className="fact"><span className="label">{t('schools.card.udise')}</span>{school.udise_code || '–'}</div></div>
            <div className="col-sm-6 col-lg-3"><div className="fact"><span className="label">{t('schools.card.principal')}</span>{school.principal_name}</div></div>
            <div className="col-sm-6 col-lg-3"><div className="fact"><span className="label">{t('schools.card.contact')}</span>{school.contact_name}<div className="text-muted text-break">{school.contact_email}</div></div></div>
          </div>
          {school.status === 'pending' && (
            <div className="alert alert-warning d-flex gap-3 align-items-start mt-3 mb-0">
              <i className="bi bi-hourglass-split fs-4" aria-hidden="true" />
              <div><strong>{t('schools.card.pendingTitle')}</strong><div className="small">{t('schools.card.pendingText', { email: school.contact_email })}</div></div>
            </div>
          )}
          {school.status === 'rejected' && (
            <div className="alert alert-danger d-flex gap-3 align-items-start mt-3 mb-0">
              <i className="bi bi-x-octagon fs-4" aria-hidden="true" />
              <div>
                <strong>{t('schools.card.rejectedTitle')}</strong>
                {school.rejection_reason && <div className="small"><strong>{t('schools.card.reason')}:</strong> {school.rejection_reason}</div>}
                <div className="small">{t('schools.card.rejectedText')}</div>
              </div>
            </div>
          )}
          {school.status === 'verified' && school.verified_at && (
            <p className="small text-success mt-3 mb-0"><i className="bi bi-patch-check me-1" aria-hidden="true" />{t('schools.card.verifiedOn', { date: formatDate(school.verified_at) })}</p>
          )}
        </div>
      </div>
    );
  }
}

export const SchoolCard = withI18n(SchoolCardBase);
