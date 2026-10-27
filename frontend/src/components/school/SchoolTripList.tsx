import * as React from 'react';
import { Link } from 'react-router-dom';
import { tripStatus } from '../../api/schools';
import type { SchoolTrip } from '../../api/types';
import { withI18n, WithI18nProps } from '../../i18n';
import { formatDate, formatDateTime, formatINR, formatTime } from '../../utils/format';
import { StatusBadge } from '../Common';

interface SchoolTripListProps extends WithI18nProps {
  trips: SchoolTrip[];
  busyId: number | null;
  onCancel: (trip: SchoolTrip) => void;
}

const PAID = ['confirmed', 'checked_in'];

/** The school's class trips with status badges and pay / ticket / cancel actions. */
class SchoolTripListBase extends React.Component<SchoolTripListProps> {
  private renderTrip(trip: SchoolTrip): React.ReactNode {
    const { busyId, onCancel } = this.props;
    const { t } = this.props.i18n;
    const st = tripStatus(trip.status);
    const b = trip.booking;
    const paid = !!b && PAID.includes(b.status);
    const lapsed = trip.status === 'approved' && !!b && (b.status === 'expired' || (b.status === 'pending' && !trip.can_pay));
    const amount = trip.quoted_amount ?? trip.estimated_amount;
    const longDate = { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' } as const;
    return (
      <div key={trip.id} className={`card border-0 shadow-sm mb-3 school-trip school-trip-${trip.status}`}>
        <div className="card-body">
          <div className="d-flex justify-content-between flex-wrap gap-2">
            <div>
              <div className="small text-muted"><span className="ref">{trip.reference}</span> · {t('schools.list.sent', { when: formatDateTime(trip.created_at) })}</div>
              <h3 className="h5 mb-1">
                <Link to={`/museums/${trip.museum_slug}`} className="text-reset">{trip.museum_name}</Link>
                <span className="text-muted fw-normal">, {trip.city_name}</span>
              </h3>
              <div className="small">
                <i className="bi bi-people me-1" aria-hidden="true" />
                {t('schools.list.class', { grades: trip.grades })} · {t('schools.list.people', { s: trip.students, t: trip.teachers, h: trip.helpers })}
              </div>
              <div className="small text-muted">
                <i className="bi bi-calendar-event me-1" aria-hidden="true" />
                {trip.approved_date
                  ? formatDate(trip.approved_date, longDate)
                  : <>{formatDate(trip.preferred_date, longDate)}{trip.alternative_date && ` ${t('schools.list.or', { date: formatDate(trip.alternative_date) })}`}</>}
                {' · '}{b?.slot_start ? `${formatTime(b.slot_start)} – ${formatTime(b.slot_end)}` : t(`schools.slot.${trip.slot_preference}`)}
                {trip.guide_language && <> · <i className="bi bi-translate me-1" aria-hidden="true" />{t('schools.list.guideReq', { lang: t(`schools.guide.${trip.guide_language}`) })}</>}
              </div>
            </div>
            <div className="text-end">
              <span className={`badge ${st.bg}`}>{t(`schools.tripStatus.${trip.status}`)}</span>
              <div className="small mt-2">
                <span className="text-muted">{trip.quoted_amount !== null ? t('schools.list.amount') : t('schools.list.estimate')}: </span>
                <strong>{Number(amount) === 0 ? t('schools.est.free') : formatINR(amount)}</strong>
              </div>
              {b && trip.status !== 'declined' && <div className="mt-1"><span className="ref small me-1">{b.reference}</span><StatusBadge status={b.status} /></div>}
            </div>
          </div>

          {trip.status === 'submitted' && (
            <p className="small text-muted mt-3 mb-0"><i className="bi bi-hourglass-split me-1" aria-hidden="true" />{t('schools.list.waiting')}</p>
          )}
          {trip.staff_note && (trip.status === 'approved' || trip.status === 'declined' || trip.status === 'completed') && (
            <div className="alert alert-light border small mt-3 mb-0">
              <strong>{trip.status === 'declined' ? t('schools.list.reason') : t('schools.list.note')}:</strong> {trip.staff_note}
            </div>
          )}
          {trip.can_pay && b?.pay_by && (
            <p className="small mt-3 mb-0"><i className="bi bi-credit-card me-1" aria-hidden="true" />{t('schools.list.payBy', { when: formatDateTime(b.pay_by) })}</p>
          )}
          {lapsed && <div className="alert alert-warning small mt-3 mb-0">{t('schools.list.expired')}</div>}
          {paid && trip.status === 'approved' && (
            <p className="small text-success mt-3 mb-0"><i className="bi bi-upc-scan me-1" aria-hidden="true" />{t('schools.list.paid')}</p>
          )}

          {(trip.can_pay || paid || trip.can_cancel) && (
            <div className="d-flex gap-2 flex-wrap mt-3">
              {trip.can_pay && b && (
                <Link to={`/checkout/${b.reference}`} className="btn btn-sm btn-accent"><i className="bi bi-credit-card me-1" aria-hidden="true" />{t('schools.list.pay')}</Link>
              )}
              {paid && b && (
                <Link to={`/tickets/${b.reference}`} className="btn btn-sm btn-outline-primary"><i className="bi bi-upc-scan me-1" aria-hidden="true" />{t('schools.list.ticket')}</Link>
              )}
              {trip.can_cancel && (
                <button type="button" className="btn btn-sm btn-outline-danger" disabled={busyId === trip.id} onClick={() => onCancel(trip)}>
                  {busyId === trip.id ? t('schools.list.cancelling') : t('schools.list.cancel')}
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }

  public render(): React.ReactNode {
    return <>{this.props.trips.map((trip) => this.renderTrip(trip))}</>;
  }
}

export default withI18n(SchoolTripListBase);
