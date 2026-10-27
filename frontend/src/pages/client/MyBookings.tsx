import * as React from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import type { Booking, Paginated } from '../../api/types';
import { Empty, Loader, Pagination, StatusBadge } from '../../components/Common';
import { MyWaitlist } from '../../components/WaitlistButton';
import { formatDate, formatINR, formatTime, isoDate } from '../../utils/format';
import { withI18n, WithI18nProps } from '../../i18n';
import { withRouter, WithRouterProps } from '../../utils/withRouter';
import { placeLocation } from '../../utils/format';

type Tab = 'upcoming' | 'past';

type MyBookingsProps = WithRouterProps & WithI18nProps;

interface MyBookingsState {
  tab: Tab;
  page: number;
  data: Paginated<Booking> | null;
}

class MyBookings extends React.Component<MyBookingsProps, MyBookingsState> {
  public state: MyBookingsState = { tab: 'upcoming', page: 1, data: null };

  private mounted = false;
  private requestId = 0;

  public componentDidMount(): void {
    this.mounted = true;
    this.load();
  }

  public componentDidUpdate(_prevProps: MyBookingsProps, prevState: MyBookingsState): void {
    if (prevState.tab !== this.state.tab || prevState.page !== this.state.page) this.load();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private load(): void {
    const { tab, page } = this.state;
    const id = ++this.requestId;
    this.setState({ data: null });
    const today = isoDate(0);
    const params =
      tab === 'upcoming'
        ? { mine: 1, page, visit_date__gte: today, ordering: 'visit_date' }
        : { mine: 1, page, visit_date__lte: isoDate(-1), ordering: '-visit_date' };
    api.get<Paginated<Booking>>('/bookings/', { params }).then((r) => {
      if (this.mounted && id === this.requestId) this.setState({ data: r.data });
    });
  }

  private setPage = (page: number): void => this.setState({ page });

  public render(): React.ReactNode {
    const { tab, page, data } = this.state;
    const { navigate } = this.props.router;
    const { t } = this.props.i18n;
    return (
      <div className="container page py-4 py-lg-5">
        <h1 className="display-6 mb-3">{t('booking.my.title')}</h1>
        <MyWaitlist />
        <ul className="nav nav-pills mb-4">
          {(['upcoming', 'past'] as Tab[]).map((x) => (
            <li key={x} className="nav-item">
              <button type="button" className={`nav-link ${tab === x ? 'active' : ''}`} aria-current={tab === x ? 'page' : undefined} onClick={() => this.setState({ tab: x, page: 1 })}>
                <i className={`bi ${x === 'upcoming' ? 'bi-calendar-event' : 'bi-clock-history'} me-2`} aria-hidden="true" />
                {x === 'upcoming' ? t('booking.my.upcoming') : t('booking.my.past')}
              </button>
            </li>
          ))}
        </ul>

        {data === null ? (
          <Loader />
        ) : data.count === 0 ? (
          <Empty title={tab === 'upcoming' ? t('booking.my.noUpcoming') : t('booking.my.noPast')}>
            <Link to="/museums" className="btn btn-accent">{t('booking.my.explore')}</Link>
          </Empty>
        ) : (
          <>
            {data.results.map((b) => (
              <Link
                key={b.reference}
                to={b.status === 'pending' ? `/checkout/${b.reference}` : `/tickets/${b.reference}`}
                className="card border-0 shadow-sm mb-3 text-decoration-none text-body"
              >
                <div className="card-body d-flex flex-column flex-md-row justify-content-between gap-3">
                  <div className="min-w-0">
                    <div className="d-flex flex-wrap align-items-center gap-2">
                      <strong className="fs-5">{b.museum_name}</strong>
                      <StatusBadge status={b.status} />
                      {b.is_group && (
                        <span className="badge bg-accent">
                          <i className="bi bi-people-fill me-1" aria-hidden="true" />
                          {t('booking.group')}
                        </span>
                      )}
                    </div>
                    {b.is_group && b.organisation_name && (
                      <div className="small fw-semibold">
                        {b.organisation_name}
                        {b.group_type_label && <span className="text-muted fw-normal"> · {b.group_type ? t(`common.groupType.${b.group_type}`) : b.group_type_label}</span>}
                      </div>
                    )}
                    <div className="text-muted small">
                      <i className="bi bi-geo-alt me-1" aria-hidden="true" />
                      {placeLocation(b.city_name, b.state_name)} · <span className="ref">{b.reference}</span>
                    </div>
                  </div>
                  <div className="text-md-end">
                    <div><strong>{formatDate(b.visit_date, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}</strong></div>
                    <div className="text-muted small">
                      {formatTime(b.slot_start)} · {t(b.total_visitors === 1 ? 'common.group.visitors.one' : 'common.group.visitors.other', { n: b.total_visitors })} · {formatINR(b.total_amount)}
                    </div>
                    {tab === 'past' && (b.status === 'checked_in' || b.status === 'confirmed') && (
                      <button
                        type="button"
                        className="btn btn-outline-accent btn-sm mt-2"
                        onClick={(e) => {
                          e.preventDefault();
                          navigate(`/museums/${b.museum_slug}#reviews`);
                        }}
                      >
                        ★ {t('booking.my.rate')}
                      </button>
                    )}
                  </div>
                </div>
              </Link>
            ))}
            <Pagination page={page} count={data.count} onChange={this.setPage} />
          </>
        )}
      </div>
    );
  }
}

export default withRouter(withI18n(MyBookings));
