import * as React from 'react';
import { Link } from 'react-router-dom';
import { cachedGet } from '../../api/cache';
import type { MuseumSummary, Paginated, State } from '../../api/types';
import { withI18n, WithI18nProps } from '../../i18n';

/** Company and founder details shown on the page (edit here). */
export const COMPANY_NAME = 'Ancient Antiquity Heritage Pvt. Ltd.';
export const COMPANY_ADDRESS = '11, RS House, SG Highway, Ahmedabad, Gujarat 380054';
const FOUNDER_INITIALS = 'RS';

const WHAT_WE_DO = [
  { key: 'book', icon: 'bi-calendar-check' },
  { key: 'queue', icon: 'bi-hourglass-split' },
  { key: 'groups', icon: 'bi-people' },
  { key: 'heritage', icon: 'bi-bank' },
];

interface AboutState {
  places: number | null;
  states: number | null;
}

class AboutBase extends React.Component<WithI18nProps, AboutState> {
  public state: AboutState = { places: null, states: null };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    document.title = `${this.props.i18n.t('about.title')} · Ancient Antiquity`;
    // Live numbers, so the page never goes out of date as places are added.
    cachedGet<Paginated<MuseumSummary>>('/museums/', undefined, (d) => {
      if (this.mounted) this.setState({ places: d.count });
    }).catch(() => undefined);
    cachedGet<State[]>('/states/', undefined, (states) => {
      if (this.mounted) this.setState({ states: states.filter((s) => s.museum_count > 0).length });
    }).catch(() => undefined);
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { places, states } = this.state;
    const stats = [
      { value: places === null ? '…' : String(places), label: t('about.stat.places'), icon: 'bi-building' },
      { value: states === null ? '…' : String(states), label: t('about.stat.states'), icon: 'bi-map' },
      { value: '2', label: t('about.stat.languages'), icon: 'bi-translate' },
      { value: '100%', label: t('about.stat.paperless'), icon: 'bi-upc-scan' },
    ];

    return (
      <div className="about-page">
        <section className="about-hero">
          <div className="container py-5">
            <div className="col-lg-9">
              <span className="badge bg-accent mb-3">{t('about.title')}</span>
              <h1 className="display-5 mb-3">{t('about.heroTitle')}</h1>
              <p className="lead mb-0">{t('about.heroText')}</p>
            </div>
          </div>
        </section>

        <div className="container page py-5">
          <div className="row g-3 mb-5 about-stats">
            {stats.map((s) => (
              <div className="col-6 col-lg-3" key={s.label}>
                <div className="card border-0 shadow-sm h-100 text-center p-3">
                  <i className={`bi ${s.icon} fs-3 text-accent`} aria-hidden="true" />
                  <div className="stat-value mt-1">{s.value}</div>
                  <div className="small text-muted">{s.label}</div>
                </div>
              </div>
            ))}
          </div>

          <div className="row g-5 align-items-start mb-5">
            <div className="col-lg-7">
              <h2 className="mb-3">{t('about.storyTitle')}</h2>
              <p>{t('about.story1')}</p>
              <p className="mb-0">{t('about.story2')}</p>
            </div>
            <div className="col-lg-5">
              <h2 className="mb-3">{t('about.teamTitle')}</h2>
              <div className="card border-0 shadow-sm founder-card">
                <div className="card-body p-4">
                  <div className="d-flex align-items-center gap-3 mb-3">
                    <span className="founder-avatar" aria-hidden="true">{FOUNDER_INITIALS}</span>
                    <div>
                      <div className="h4 mb-0">{t('about.founder.name')}</div>
                      <div className="text-accent fw-semibold">{t('about.founder.role')}</div>
                      <div className="small text-muted">
                        <i className="bi bi-geo-alt me-1" aria-hidden="true" />
                        {t('about.founder.place')}
                      </div>
                    </div>
                  </div>
                  <p className="mb-0">{t('about.founder.bio')}</p>
                </div>
              </div>
            </div>
          </div>

          <h2 className="mb-3">{t('about.whatTitle')}</h2>
          <div className="row g-3 mb-5">
            {WHAT_WE_DO.map((w) => (
              <div className="col-sm-6 col-lg-3" key={w.key}>
                <div className="card border-0 shadow-sm h-100 p-3">
                  <span className="what-icon mb-2"><i className={`bi ${w.icon}`} aria-hidden="true" /></span>
                  <h3 className="h6 fw-bold mb-1">{t(`about.what.${w.key}.title`)}</h3>
                  <p className="small text-muted mb-0">{t(`about.what.${w.key}.text`)}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="row g-4">
            <div className="col-lg-5">
              <div className="card border-0 shadow-sm h-100">
                <div className="card-body p-4">
                  <h2 className="h5 mb-3">{t('about.companyTitle')}</h2>
                  <div className="fw-semibold">{COMPANY_NAME}</div>
                  <div className="text-muted">
                    <i className="bi bi-geo-alt me-1" aria-hidden="true" />
                    {COMPANY_ADDRESS}
                  </div>
                </div>
              </div>
            </div>
            <div className="col-lg-7">
              <div className="card border-0 about-cta h-100">
                <div className="card-body p-4 d-flex flex-column justify-content-center">
                  <h2 className="h4 mb-2">{t('about.ctaTitle')}</h2>
                  <p className="mb-3">{t('about.ctaText')}</p>
                  <div className="d-flex flex-wrap gap-2">
                    <Link to="/museums" className="btn btn-accent">
                      <i className="bi bi-compass me-1" aria-hidden="true" />
                      {t('about.ctaExplore')}
                    </Link>
                    <Link to="/contact" className="btn btn-light">
                      <i className="bi bi-envelope me-1" aria-hidden="true" />
                      {t('about.ctaContact')}
                    </Link>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }
}

export default withI18n(AboutBase);
