import * as React from 'react';
import { NavLink } from 'react-router-dom';
import { withAuth, WithAuthProps } from '../context/AuthContext';
import { LANGS, withI18n, WithI18nProps } from '../i18n';
import { withRouter, WithRouterProps } from '../utils/withRouter';
import { FOREIGN_CURRENCIES, getCurrency, loadFxRates, onCurrencyChange, setCurrency } from '../api/donations';
import Logo from './Logo';

/** Two letters for the round avatar: first + last name, or the email when no name is set. */
function initials(first: string, last: string, email: string): string {
  const fromName = `${first.trim().charAt(0)}${last.trim().charAt(0)}`;
  return (fromName || email.charAt(0)).toUpperCase();
}

interface NavbarProps extends WithAuthProps, WithRouterProps, WithI18nProps {}

interface NavbarState {
  open: boolean;
  accountOpen: boolean;
  langOpen: boolean;
  moreOpen: boolean;
  /** Currency for the ≈ price hints (INR = none). */
  currency: string;
  currencies: string[];
}

class NavbarBase extends React.Component<NavbarProps, NavbarState> {
  public state: NavbarState = {
    open: false, accountOpen: false, langOpen: false, moreOpen: false, currency: getCurrency(), currencies: [...FOREIGN_CURRENCIES],
  };

  private unsubscribeCurrency: (() => void) | null = null;

  private account = React.createRef<HTMLDivElement>();
  private langMenu = React.createRef<HTMLDivElement>();
  private moreMenu = React.createRef<HTMLDivElement>();

  public componentDidMount(): void {
    document.addEventListener('mousedown', this.onOutside);
    document.addEventListener('keydown', this.onKey);
    this.unsubscribeCurrency = onCurrencyChange(() => this.setState({ currency: getCurrency() }));
    loadFxRates().then((fx) => {
      if (fx) this.setState({ currencies: FOREIGN_CURRENCIES.filter((c) => c in fx.rates) });
    });
  }

  public componentWillUnmount(): void {
    document.removeEventListener('mousedown', this.onOutside);
    document.removeEventListener('keydown', this.onKey);
    this.unsubscribeCurrency?.();
  }

  private onOutside = (e: MouseEvent): void => {
    const target = e.target as Node;
    if (this.state.accountOpen && !this.account.current?.contains(target)) this.setState({ accountOpen: false });
    if (this.state.langOpen && !this.langMenu.current?.contains(target)) this.setState({ langOpen: false });
    if (this.state.moreOpen && !this.moreMenu.current?.contains(target)) this.setState({ moreOpen: false });
  };

  private onKey = (e: KeyboardEvent): void => {
    if (e.key === 'Escape') this.setState({ accountOpen: false, langOpen: false, moreOpen: false });
  };

  private close = (): void => {
    this.setState({ open: false, accountOpen: false, langOpen: false, moreOpen: false });
  };

  private toggleMore = (e: React.MouseEvent<HTMLButtonElement>): void => {
    e.stopPropagation(); // keep the mobile menu open while the list expands
    this.setState({ moreOpen: !this.state.moreOpen, accountOpen: false, langOpen: false });
  };

  /** Less-used visitor pages, grouped so the top bar stays on one line. */
  private renderMore(): React.ReactNode {
    const { t } = this.props.i18n;
    const items = [
      { to: '/passes', icon: 'bi-collection', label: t('passes.title') },
      { to: '/membership', icon: 'bi-award', label: t('shop.membership.title') },
      { to: '/schools', icon: 'bi-book', label: t('schools.title') },
      { to: '/donate', icon: 'bi-heart', label: t('common.nav.donate') },
      { to: '/about', icon: 'bi-info-circle', label: t('common.footer.about') },
    ];
    const active = items.some((i) => this.props.router.location.pathname.startsWith(i.to));
    return (
      <div className="nav-item dropdown more-menu" ref={this.moreMenu}>
        <button
          type="button"
          className={`btn btn-link nav-link dropdown-toggle text-start ${active ? 'active' : ''}`}
          aria-expanded={this.state.moreOpen}
          aria-haspopup="true"
          onClick={this.toggleMore}
        >
          <i className="bi bi-grid me-1" aria-hidden="true" />
          {t('common.nav.more')}
        </button>
        <div className={`dropdown-menu shadow ${this.state.moreOpen ? 'show' : ''}`}>
          {items.map((i) => (
            <NavLink key={i.to} to={i.to} className="dropdown-item">
              <i className={`bi ${i.icon}`} aria-hidden="true" />
              {i.label}
            </NavLink>
          ))}
        </div>
      </div>
    );
  }

  private toggleAccount = (e: React.MouseEvent<HTMLButtonElement>): void => {
    e.stopPropagation(); // keep the mobile menu open while the account list expands
    this.setState({ accountOpen: !this.state.accountOpen });
  };

  private toggle = (): void => {
    this.setState({ open: !this.state.open });
  };

  private onLogout = (): void => {
    this.props.auth.logout();
    this.props.router.navigate('/');
  };

  private toggleLangMenu = (e: React.MouseEvent<HTMLButtonElement>): void => {
    e.stopPropagation(); // keep the mobile menu open while the panel expands
    this.setState({ langOpen: !this.state.langOpen, accountOpen: false, moreOpen: false });
  };

  /** One "language · currency" button with a two-part panel (currency only changes the ≈ price hints). */
  private renderPreferences(): React.ReactNode {
    const { lang, setLang, t } = this.props.i18n;
    const { currency, currencies } = this.state;
    const current = LANGS.find((l) => l.value === lang) ?? LANGS[0];
    const currencyLabel = (code: string) => (code === 'INR' ? '₹ INR' : t(`giving.fx.code.${code}`));
    return (
      <div className="nav-item dropdown prefs-menu ms-lg-2 my-2 my-lg-0 align-self-start align-self-lg-center" ref={this.langMenu}>
        <button
          type="button"
          className="btn btn-sm prefs-toggle d-flex align-items-center gap-2"
          aria-expanded={this.state.langOpen}
          aria-haspopup="true"
          aria-label={`${t('common.lang.choose')} / ${t('giving.fx.picker')}: ${current.label}, ${currencyLabel(currency)}`}
          title={`${current.label} · ${currencyLabel(currency)}`}
          onClick={this.toggleLangMenu}
        >
          <i className="bi bi-globe2" aria-hidden="true" />
          <span className="prefs-code">{current.value.toUpperCase()}</span>
          {currency !== 'INR' && <span className="prefs-code text-muted">{currency}</span>}
          <i className={`bi bi-chevron-${this.state.langOpen ? 'up' : 'down'} small`} aria-hidden="true" />
        </button>
        <div className={`dropdown-menu dropdown-menu-end shadow prefs-panel ${this.state.langOpen ? 'show' : ''}`}>
          <div className="prefs-col">
            <div className="prefs-heading"><i className="bi bi-translate" aria-hidden="true" /> {t('common.lang.choose')}</div>
            {LANGS.map((l) => (
              <button
                key={l.value}
                type="button"
                className={`dropdown-item ${l.value === lang ? 'active' : ''}`}
                aria-current={l.value === lang}
                onClick={() => setLang(l.value)}
              >
                <span lang={l.value}>{l.label}</span>
                {l.value !== 'en' && <span className="small text-muted">{l.english}</span>}
                {l.value === lang && <i className="bi bi-check2 ms-auto" aria-hidden="true" />}
              </button>
            ))}
          </div>
          <div className="prefs-col">
            <div className="prefs-heading"><i className="bi bi-currency-exchange" aria-hidden="true" /> {t('giving.fx.picker')}</div>
            {['INR', ...currencies].map((code) => (
              <button
                key={code}
                type="button"
                className={`dropdown-item ${code === currency ? 'active' : ''}`}
                aria-current={code === currency}
                onClick={() => setCurrency(code)}
              >
                <span>{currencyLabel(code)}</span>
                {code === currency && <i className="bi bi-check2 ms-auto" aria-hidden="true" />}
              </button>
            ))}
            <p className="prefs-hint">{t('giving.fx.pickerHint')}</p>
          </div>
        </div>
      </div>
    );
  }

  public render(): React.ReactNode {
    const { user } = this.props.auth;
    const { t } = this.props.i18n;
    const { open } = this.state;

    return (
      <nav className="navbar navbar-expand-lg navbar-light bg-white sticky-top shadow-sm">
        <div className="container">
          <Logo />
          <button
            className="navbar-toggler"
            type="button"
            aria-controls="main-nav"
            aria-label={t('common.nav.menu')}
            aria-expanded={open}
            onClick={this.toggle}
          >
            <span className="navbar-toggler-icon" />
          </button>
          <div id="main-nav" className={`collapse navbar-collapse ${open ? 'show' : ''}`} onClick={this.close}>
            <div className="navbar-nav ms-auto align-items-lg-center gap-lg-1">
              <NavLink to="/museums" className="nav-link">
                <i className="bi bi-compass me-1" aria-hidden="true" />
                {t('common.nav.explore')}
              </NavLink>
              <NavLink to="/events" className="nav-link">
                <i className="bi bi-calendar-event me-1" aria-hidden="true" />
                {t('events.title')}
              </NavLink>
              <NavLink to="/map" className="nav-link">
                <i className="bi bi-map me-1" aria-hidden="true" />
                {t('trips.map.title')}
              </NavLink>
              {this.renderMore()}
              {user ? (
                <>
                  <NavLink to="/my-bookings" className="nav-link">
                    <i className="bi bi-calendar-check me-1" aria-hidden="true" />
                    {t('common.nav.myBookings')}
                  </NavLink>
                  <div className="nav-item dropdown account-menu" ref={this.account}>
                    <button
                      type="button"
                      className="btn account-toggle d-flex align-items-center gap-2"
                      aria-expanded={this.state.accountOpen}
                      aria-haspopup="true"
                      aria-label={t('common.nav.account')}
                      onClick={this.toggleAccount}
                    >
                      <span className="avatar" aria-hidden="true">{initials(user.first_name, user.last_name, user.email)}</span>
                      <span className="d-lg-none d-xl-inline">{user.first_name || t('common.nav.account')}</span>
                      <i className={`bi bi-chevron-${this.state.accountOpen ? 'up' : 'down'} small`} aria-hidden="true" />
                    </button>
                    <div className={`dropdown-menu dropdown-menu-end shadow ${this.state.accountOpen ? 'show' : ''}`}>
                      <div className="account-head">
                        <span className="avatar avatar-lg" aria-hidden="true">{initials(user.first_name, user.last_name, user.email)}</span>
                        <div className="min-w-0">
                          <div className="fw-semibold text-truncate">{`${user.first_name} ${user.last_name}`.trim() || t('common.nav.account')}</div>
                          <div className="small text-muted text-truncate">{user.email}</div>
                        </div>
                      </div>
                      <div className="dropdown-divider" />
                      <NavLink to="/trips" className="dropdown-item">
                        <i className="bi bi-signpost-split" aria-hidden="true" />
                        {t('trips.planner.title')}
                      </NavLink>
                      <NavLink to="/favourites" className="dropdown-item">
                        <i className="bi bi-heart" aria-hidden="true" />
                        {t('trips.fav.title')}
                      </NavLink>
                      <NavLink to="/profile" className="dropdown-item">
                        <i className="bi bi-person" aria-hidden="true" />
                        {t('common.nav.profile')}
                      </NavLink>
                      {user.role === 'partner' && (
                        <NavLink to="/partner" className="dropdown-item">
                          <i className="bi bi-bar-chart" aria-hidden="true" />
                          {t('common.nav.partner')}
                        </NavLink>
                      )}
                      {user.is_panel_user && (
                        <NavLink to="/admin" className="dropdown-item">
                          <i className="bi bi-speedometer2" aria-hidden="true" />
                          {t('common.nav.admin')}
                        </NavLink>
                      )}
                      <div className="dropdown-divider" />
                      <button type="button" className="dropdown-item text-danger" onClick={this.onLogout}>
                        <i className="bi bi-box-arrow-right" aria-hidden="true" />
                        {t('common.nav.logout')}
                      </button>
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <NavLink to="/login" className="nav-link">
                    {t('common.nav.login')}
                  </NavLink>
                  <NavLink to="/register" className="btn btn-accent btn-sm ms-lg-2 my-2 my-lg-0 align-self-start align-self-lg-center">
                    {t('common.nav.signup')}
                  </NavLink>
                </>
              )}
              {this.renderPreferences()}
            </div>
          </div>
        </div>
      </nav>
    );
  }
}

export default withRouter(withAuth(withI18n(NavbarBase)));
