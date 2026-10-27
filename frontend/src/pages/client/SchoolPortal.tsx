import * as React from 'react';
import { Link } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import { cancelTrip, getMySchool, listTrips, STUDENTS_PER_TEACHER } from '../../api/schools';
import type { Paginated, School, SchoolTrip, State } from '../../api/types';
import { Loader, Pagination } from '../../components/Common';
import ClassTripForm from '../../components/school/ClassTripForm';
import { SchoolCard, SchoolForm } from '../../components/school/SchoolRegistration';
import SchoolTripList from '../../components/school/SchoolTripList';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { withI18n, WithI18nProps } from '../../i18n';
import { withRouter, WithRouterProps } from '../../utils/withRouter';

type SchoolPortalProps = WithRouterProps & WithAuthProps & WithI18nProps;

interface SchoolPortalState {
  /** undefined: loading; null: no school registered yet. */
  school: School | null | undefined;
  states: State[];
  editing: boolean;
  error: string;
  trips: Paginated<SchoolTrip> | null;
  page: number;
  busyId: number | null;
  listError: string;
  created: SchoolTrip | null;
}

const BENEFITS: { key: string; icon: string }[] = [
  { key: 'price', icon: 'bi-cash-coin' },
  { key: 'teachers', icon: 'bi-person-check' },
  { key: 'qr', icon: 'bi-upc-scan' },
  { key: 'guide', icon: 'bi-translate' },
];

/** /schools: school trip portal for teachers (register the school, plan class trips, pay and get one ticket). */
class SchoolPortal extends React.Component<SchoolPortalProps, SchoolPortalState> {
  public state: SchoolPortalState = {
    school: undefined, states: [], editing: false, error: '', trips: null, page: 1, busyId: null, listError: '',
    created: null,
  };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    if (this.props.auth.user) this.loadSchool();
  }

  public componentDidUpdate(prevProps: SchoolPortalProps, prevState: SchoolPortalState): void {
    const user = this.props.auth.user;
    if (user?.id !== prevProps.auth.user?.id) {
      if (user) this.loadSchool();
      else this.setState({ school: undefined, trips: null });
    }
    if (prevState.page !== this.state.page) this.loadTrips();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private loadSchool(): void {
    getMySchool()
      .then((school) => {
        if (!this.mounted) return;
        this.setState({ school, error: '' });
        if (school) this.loadTrips();
        if (!school) this.loadStates();
      })
      .catch((err) => this.mounted && this.setState({ school: null, error: errorMessage(err) }));
  }

  private loadStates(): void {
    if (this.state.states.length) return;
    api
      .get<State[]>('/states/')
      .then((r) => this.mounted && this.setState({ states: [...r.data].sort((a, b) => a.name.localeCompare(b.name)) }))
      .catch(() => undefined);
  }

  private loadTrips(): void {
    listTrips({ mine: 1, page: this.state.page })
      .then((trips) => this.mounted && this.setState({ trips, listError: '' }))
      .catch((err) => this.mounted && this.setState({ listError: errorMessage(err), trips: { count: 0, next: null, previous: null, results: [] } }));
  }

  private onSchoolSaved = (school: School): void => {
    this.setState({ school, editing: false });
    window.scrollTo({ top: 0, behavior: 'smooth' });
    this.loadTrips();
  };

  private onTripCreated = (trip: SchoolTrip): void => {
    this.setState({ created: trip, page: 1 });
    this.loadTrips();
    document.getElementById('school-trips')?.scrollIntoView({ behavior: 'smooth' });
  };

  private cancel = async (trip: SchoolTrip): Promise<void> => {
    if (!window.confirm(this.props.i18n.t('schools.list.confirmCancel', { ref: trip.reference }))) return;
    this.setState({ busyId: trip.id, listError: '' });
    try {
      const updated = await cancelTrip(trip.id);
      if (!this.mounted) return;
      this.setState((s) => ({
        busyId: null,
        trips: s.trips && { ...s.trips, results: s.trips.results.map((x) => (x.id === updated.id ? updated : x)) },
      }));
    } catch (err) {
      if (this.mounted) this.setState({ busyId: null, listError: errorMessage(err) });
    }
  };

  private startEdit = (): void => {
    this.loadStates();
    this.setState({ editing: true });
  };

  private renderLanding(): React.ReactNode {
    const { t } = this.props.i18n;
    return (
      <>
        <section className="school-hero">
          <div className="container py-5">
            <div className="row align-items-center g-4">
              <div className="col-lg-7">
                <div className="school-kicker">{t('schools.kicker')}</div>
                <h1 className="display-5 mb-3">{t('schools.title')}</h1>
                <p className="lead mb-0">{t('schools.lead')}</p>
              </div>
              <div className="col-lg-5">
                <div className="card border-0 shadow-sm">
                  <div className="card-body">
                    <h2 className="h6 text-uppercase text-muted mb-3">{t('schools.how.title')}</h2>
                    <ol className="school-steps mb-0">
                      {[1, 2, 3, 4].map((n) => <li key={n}>{t(`schools.how.step${n}`)}</li>)}
                    </ol>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>
        <div className="container">
          <div className="row g-3 school-benefits">
            {BENEFITS.map((b) => (
              <div key={b.key} className="col-sm-6 col-lg-3">
                <div className="card border-0 shadow-sm h-100">
                  <div className="card-body">
                    <div className="school-benefit-icon mb-2"><i className={`bi ${b.icon}`} aria-hidden="true" /></div>
                    <h3 className="h6">{t(`schools.benefit.${b.key}.title`)}</h3>
                    <p className="small text-muted mb-0">{t(`schools.benefit.${b.key}.text`, { n: STUDENTS_PER_TEACHER })}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </>
    );
  }

  private renderSignIn(): React.ReactNode {
    const { t } = this.props.i18n;
    return (
      <div className="card border-0 shadow-sm text-center">
        <div className="card-body p-4 p-lg-5">
          <i className="bi bi-book display-6 text-primary" aria-hidden="true" />
          <h2 className="h4 mt-2">{t('schools.signIn.title')}</h2>
          <p className="text-muted">{t('schools.signIn.text')}</p>
          <Link to="/login" state={{ from: this.props.router.location.pathname }} className="btn btn-accent">
            <i className="bi bi-box-arrow-in-right me-1" aria-hidden="true" />{t('schools.signIn.button')}
          </Link>
        </div>
      </div>
    );
  }

  private renderMain(): React.ReactNode {
    const { auth } = this.props;
    const { school, states, editing, error, trips, page, listError, created } = this.state;
    const { t } = this.props.i18n;
    if (auth.loading) return <Loader />;
    if (!auth.user) return this.renderSignIn();
    if (school === undefined) return error ? <div className="alert alert-danger">{error}</div> : <Loader />;
    if (school === null || editing) {
      return (
        <SchoolForm
          key={school ? `edit-${school.id}` : 'new'}
          user={auth.user}
          states={states}
          school={school}
          onSaved={this.onSchoolSaved}
          onCancel={school ? () => this.setState({ editing: false }) : undefined}
        />
      );
    }
    return (
      <>
        <SchoolCard school={school} onEdit={this.startEdit} />
        {school.status === 'verified' && (
          <div className="mt-4">
            <ClassTripForm onCreated={this.onTripCreated} />
          </div>
        )}
        <h2 className="h3 mt-5 mb-3" id="school-trips">{t('schools.list.title')}</h2>
        {created && (
          <div className="alert alert-success d-flex gap-3 align-items-start">
            <i className="bi bi-check-circle fs-4" aria-hidden="true" />
            <div>{t('schools.trip.created', { ref: created.reference, email: created.contact_email })}</div>
          </div>
        )}
        {listError && <div className="alert alert-danger">{listError}</div>}
        {trips === null ? (
          <Loader />
        ) : trips.count === 0 ? (
          <p className="text-muted">{t('schools.list.empty')}</p>
        ) : (
          <>
            <SchoolTripList trips={trips.results} busyId={this.state.busyId} onCancel={this.cancel} />
            <Pagination page={page} count={trips.count} onChange={(p) => this.setState({ page: p })} />
          </>
        )}
      </>
    );
  }

  public render(): React.ReactNode {
    return (
      <div className="page pb-5">
        {this.renderLanding()}
        <div className="container mt-4 mt-lg-5">{this.renderMain()}</div>
      </div>
    );
  }
}

export default withRouter(withAuth(withI18n(SchoolPortal)));
