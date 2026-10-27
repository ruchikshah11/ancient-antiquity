import * as React from 'react';
import { Link, NavLink, Outlet } from 'react-router-dom';
import { Loader } from '../../components/Common';
import Logo from '../../components/Logo';
import { TwoFactorSetupBanner } from '../client/Profile';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { withRouter, WithRouterProps } from '../../utils/withRouter';

interface AdminLayoutProps extends WithAuthProps, WithRouterProps {}

interface AdminLayoutState {
  /** Sidebar folded to an icon-only rail (desktop); remembered per browser. */
  collapsed: boolean;
}

const COLLAPSE_KEY = 'aa_admin_sidebar_collapsed';

class AdminLayoutPage extends React.Component<AdminLayoutProps, AdminLayoutState> {
  public state: AdminLayoutState = { collapsed: (() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === '1';
    } catch {
      return false;
    }
  })() };

  private toggleSidebar = (): void => {
    const collapsed = !this.state.collapsed;
    this.setState({ collapsed });
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0');
    } catch {
      /* storage unavailable */
    }
  };

  private onLogout = (e: React.MouseEvent<HTMLAnchorElement>): void => {
    e.preventDefault();
    this.props.auth.logout();
    this.props.router.navigate('/');
  };

  public render(): React.ReactNode {
    const { user } = this.props.auth;
    const { collapsed } = this.state;

    return (
      <div className={`admin-shell ${collapsed ? 'collapsed' : ''}`}>
        <aside className="admin-sidebar">
          <div className="admin-sidebar-top">
            <Logo to="/admin" />
            <button
              type="button"
              className="sidebar-toggle"
              onClick={this.toggleSidebar}
              aria-label={collapsed ? 'Expand menu' : 'Collapse menu'}
              aria-expanded={!collapsed}
              title={collapsed ? 'Expand menu' : 'Collapse menu'}
            >
              <i className={`bi ${collapsed ? 'bi-chevron-double-right' : 'bi-chevron-double-left'}`} aria-hidden="true" />
            </button>
          </div>
          {/* Links scroll inside the sidebar; the logo and the sign-out block stay in place. */}
          <nav className="nav flex-column admin-nav" aria-label="Admin">
            <div className="nav-section">Daily work</div>
              <NavLink to="/admin" end className="nav-link" title={collapsed ? "Dashboard" : undefined}>
                <i className="bi bi-speedometer2" aria-hidden="true" /> <span className="nav-label">Dashboard</span>
              </NavLink>
              <NavLink to="/admin/counter" className="nav-link" title={collapsed ? "Ticket counter" : undefined}>
                <i className="bi bi-cash-coin" aria-hidden="true" /> <span className="nav-label">Ticket counter</span>
              </NavLink>
              <NavLink to="/admin/checkin" className="nav-link" title={collapsed ? "Gate check-in" : undefined}>
                <i className="bi bi-upc-scan" aria-hidden="true" /> <span className="nav-label">Gate check-in</span>
              </NavLink>
              <NavLink to="/admin/occupancy" className="nav-link" title={collapsed ? "Live occupancy" : undefined}>
                <i className="bi bi-people" aria-hidden="true" /> <span className="nav-label">Live occupancy</span>
              </NavLink>
              <NavLink to="/admin/bookings" className="nav-link" title={collapsed ? "Bookings" : undefined}>
                <i className="bi bi-journal-text" aria-hidden="true" /> <span className="nav-label">Bookings</span>
              </NavLink>
              <NavLink to="/admin/group-requests" className="nav-link" title={collapsed ? "Group requests" : undefined}>
                <i className="bi bi-people-fill" aria-hidden="true" /> <span className="nav-label">Group requests</span>
              </NavLink>
              <NavLink to="/admin/support" className="nav-link" title={collapsed ? "Support inbox" : undefined}>
                <i className="bi bi-envelope" aria-hidden="true" /> <span className="nav-label">Support inbox</span>
              </NavLink>
            <div className="nav-section">Sales</div>
              <NavLink to="/admin/events" className="nav-link" title={collapsed ? "Events" : undefined}>
                <i className="bi bi-calendar-event" aria-hidden="true" /> <span className="nav-label">Events</span>
              </NavLink>
              <NavLink to="/admin/school-trips" className="nav-link" title={collapsed ? "School trips" : undefined}>
                <i className="bi bi-journal-bookmark" aria-hidden="true" /> <span className="nav-label">School trips</span>
              </NavLink>
              <NavLink to="/admin/addons" className="nav-link" title={collapsed ? "Add-ons" : undefined}>
                <i className="bi bi-bag-plus" aria-hidden="true" /> <span className="nav-label">Add-ons</span>
              </NavLink>
              <NavLink to="/admin/promotions" className="nav-link" title={collapsed ? "Promotions" : undefined}>
                <i className="bi bi-tag" aria-hidden="true" /> <span className="nav-label">Promotions</span>
              </NavLink>
              <NavLink to="/admin/settlements" className="nav-link" title={collapsed ? "Settlements" : undefined}>
                <i className="bi bi-cash-stack" aria-hidden="true" /> <span className="nav-label">Settlements</span>
              </NavLink>
            <div className="nav-section">Insights</div>
              <NavLink to="/admin/reports" className="nav-link" title={collapsed ? "Reports" : undefined}>
                <i className="bi bi-bar-chart-line" aria-hidden="true" /> <span className="nav-label">Reports</span>
              </NavLink>
              <NavLink to="/admin/funnel" className="nav-link" title={collapsed ? "Funnel" : undefined}>
                <i className="bi bi-funnel" aria-hidden="true" /> <span className="nav-label">Funnel</span>
              </NavLink>
              <NavLink to="/admin/pricing" className="nav-link" title={collapsed ? "Pricing insights" : undefined}>
                <i className="bi bi-graph-up-arrow" aria-hidden="true" /> <span className="nav-label">Pricing insights</span>
              </NavLink>
              <NavLink to="/admin/exports" className="nav-link" title={collapsed ? "Exports" : undefined}>
                <i className="bi bi-cloud-download" aria-hidden="true" /> <span className="nav-label">Exports</span>
              </NavLink>
            {user?.is_admin_role && (
              <>
                <div className="nav-section">Administration</div>
                <NavLink to="/admin/settings" className="nav-link" title={collapsed ? "Settings" : undefined}>
                  <i className="bi bi-sliders" aria-hidden="true" /> <span className="nav-label">Settings</span>
                </NavLink>
                <NavLink to="/admin/museums" className="nav-link" title={collapsed ? "Places" : undefined}>
                  <i className="bi bi-building" aria-hidden="true" /> <span className="nav-label">Places</span>
                </NavLink>
                <NavLink to="/admin/memberships" className="nav-link" title={collapsed ? "Heritage Card" : undefined}>
                  <i className="bi bi-award" aria-hidden="true" /> <span className="nav-label">Heritage Card</span>
                </NavLink>
                <NavLink to="/admin/donations" className="nav-link" title={collapsed ? "Donations" : undefined}>
                  <i className="bi bi-heart" aria-hidden="true" /> <span className="nav-label">Donations</span>
                </NavLink>
                <NavLink to="/admin/passes" className="nav-link" title={collapsed ? "Combo passes" : undefined}>
                  <i className="bi bi-collection" aria-hidden="true" /> <span className="nav-label">Combo passes</span>
                </NavLink>
                <NavLink to="/admin/partners" className="nav-link" title={collapsed ? "Partners &amp; kiosks" : undefined}>
                  <i className="bi bi-briefcase" aria-hidden="true" /> <span className="nav-label">Partners &amp; kiosks</span>
                </NavLink>
                <NavLink to="/admin/reviews" className="nav-link" title={collapsed ? "Reviews" : undefined}>
                  <i className="bi bi-star" aria-hidden="true" /> <span className="nav-label">Reviews</span>
                </NavLink>
                <NavLink to="/admin/users" className="nav-link" title={collapsed ? "Users" : undefined}>
                  <i className="bi bi-people" aria-hidden="true" /> <span className="nav-label">Users</span>
                </NavLink>
                <NavLink to="/admin/audit" className="nav-link" title={collapsed ? "Audit log" : undefined}>
                  <i className="bi bi-shield-check" aria-hidden="true" /> <span className="nav-label">Audit log</span>
                </NavLink>
                <a className="nav-link" title={collapsed ? "Django admin" : undefined} href="/django-admin/" target="_blank" rel="noreferrer">
                  <i className="bi bi-box-arrow-up-right" aria-hidden="true" /> <span className="nav-label">Django admin</span>
                </a>
              </>
            )}
          </nav>
          <nav className="nav flex-column admin-nav-footer">
            <Link to="/" className="nav-link" title={collapsed ? "Visitor site" : undefined}>
              <i className="bi bi-arrow-left" aria-hidden="true" /> <span className="nav-label">Visitor site</span>
            </Link>
            <a href="#logout" className="nav-link" title={collapsed ? "Log out" : undefined} onClick={this.onLogout}>
              <i className="bi bi-box-arrow-right" aria-hidden="true" /> <span className="nav-label">Log out</span>
            </a>
          </nav>
          <div className="who">
            {user?.email}
            <br />
            {user?.is_admin_role ? 'Administrator' : 'Museum staff'}
          </div>
        </aside>
        <main className="admin-main">
          <TwoFactorSetupBanner />
          {/* Pages load on demand: keep the sidebar visible while a page's code downloads. */}
          <React.Suspense fallback={<Loader />}>
            <Outlet />
          </React.Suspense>
        </main>
      </div>
    );
  }
}

export default withRouter(withAuth(AdminLayoutPage));
