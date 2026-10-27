import * as React from 'react';
import { Link } from 'react-router-dom';
import { loadSiteSettings } from '../api/siteSettings';
import type { SiteSettings } from '../api/siteSettings';
import { withI18n, WithI18nProps } from '../i18n';

interface FooterState {
  site: SiteSettings | null;
}

/** Footer texts can be changed in Admin -> Settings; empty fields keep the standard translated wording. */
class Footer extends React.Component<WithI18nProps, FooterState> {
  public state: FooterState = { site: null };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    loadSiteSettings((site) => this.mounted && this.setState({ site })).catch(() => undefined);
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  public render(): React.ReactNode {
    const { t } = this.props.i18n;
    const { site } = this.state;
    const year = String(new Date().getFullYear());
    const brand = site?.footer_brand?.trim() || 'Ancient Antiquity';
    const tagline = site?.footer_tagline?.trim() || t('common.footer.tagline');
    const copyright = (site?.footer_copyright?.trim() || `© {year} ${brand}`).split('{year}').join(year);
    return (
      <footer className="bg-navy text-white-50 py-4 mt-5">
        <div className="container d-flex justify-content-between align-items-center gap-3 flex-wrap">
          <div>
            <strong className="text-white">{brand}</strong>
            <div className="small">{tagline}</div>
          </div>
          <div className="d-flex align-items-center gap-3 flex-wrap small">
            <Link to="/museums" className="link-light">{t('common.nav.explore')}</Link>
            <Link to="/my-bookings" className="link-light">{t('common.nav.myBookings')}</Link>
            <span>{copyright}</span>
          </div>
        </div>
        <div className="container mt-3 pt-3 border-top border-secondary">
          <nav className="d-flex align-items-center gap-2 flex-wrap small" aria-label={t('common.footer.legalNav')}>
            <Link to="/about" className="link-light">{t('common.footer.about')}</Link>
            <span aria-hidden="true">·</span>
            <Link to="/terms" className="link-light">{t('common.footer.terms')}</Link>
            <span aria-hidden="true">·</span>
            <Link to="/privacy" className="link-light">{t('common.footer.privacy')}</Link>
            <span aria-hidden="true">·</span>
            <Link to="/refund-policy" className="link-light">{t('common.footer.refund')}</Link>
            <span aria-hidden="true">·</span>
            <Link to="/contact" className="link-light">{t('common.footer.contact')}</Link>
            <span aria-hidden="true">·</span>
            <Link to="/donate" className="link-light">{t('common.nav.donate')}</Link>
            <span aria-hidden="true">·</span>
            <Link to="/membership" className="link-light">{t('shop.membership.title')}</Link>
            <span aria-hidden="true">·</span>
            <Link to="/schools" className="link-light">{t('schools.title')}</Link>
            <span aria-hidden="true">·</span>
            <Link to="/agent" className="link-light">{t('partners.agent.title')}</Link>
          </nav>
        </div>
      </footer>
    );
  }
}

export default withI18n(Footer);
