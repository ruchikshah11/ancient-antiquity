import * as React from 'react';
import { api, errorMessage } from '../../api/client';
import { clearApiCache } from '../../api/cache';
import type { AdminSiteSettings } from '../../api/siteSettings';
import { Loader } from '../../components/Common';
import { formatDateTime } from '../../utils/format';

type SwitchKey = 'individual_bookings_enabled' | 'group_bookings_enabled' | 'group_requests_enabled' | 'school_trips_enabled' | 'events_enabled' | 'passes_enabled';

const SWITCHES: { key: SwitchKey; label: string; help: string; icon: string }[] = [
  { key: 'individual_bookings_enabled', icon: 'bi-person', label: 'Individual tickets',
    help: 'Visitors booking entry tickets for themselves and family (up to 20). Off = every place is groups-only.' },
  { key: 'group_bookings_enabled', icon: 'bi-people', label: 'Group bookings (21-60)',
    help: 'Instant group bookings with one QR ticket for the whole group.' },
  { key: 'group_requests_enabled', icon: 'bi-people-fill', label: 'Group requests (61+)',
    help: 'Large groups asking for a quote, approved by staff.' },
  { key: 'school_trips_enabled', icon: 'bi-book', label: 'School trips',
    help: 'New class-visit requests from the school portal. Trips already approved are not affected.' },
  { key: 'events_enabled', icon: 'bi-calendar-event', label: 'Event tickets',
    help: 'Light & sound shows and other events. Each event also has its own On sale switch.' },
  { key: 'passes_enabled', icon: 'bi-collection', label: 'Combo passes',
    help: 'Multi-place passes. Each pass also has its own Active switch.' },
];

const FOOTER_FIELDS: { key: 'footer_brand' | 'footer_tagline' | 'footer_copyright'; label: string; placeholder: string; help: string }[] = [
  { key: 'footer_brand', label: 'Name', placeholder: 'Ancient Antiquity', help: 'Bold name at the left of the footer.' },
  { key: 'footer_tagline', label: 'Tagline', placeholder: 'Book tickets to museums, forts, palaces and monuments across India.',
    help: 'Empty = the standard line, translated into every language.' },
  { key: 'footer_copyright', label: 'Copyright line', placeholder: '© {year} Ancient Antiquity',
    help: 'Type {year} for the current year (updates by itself), or a fixed year such as © 2026.' },
];

interface SiteSettingsState {
  data: AdminSiteSettings | null;
  message: string;
  footer: Record<'footer_brand' | 'footer_tagline' | 'footer_copyright', string>;
  saving: SwitchKey | 'message' | 'footer' | null;
  error: string;
  notice: string;
}

/** Admin -> Settings: site-wide booking switches. Each place's own switches are in Places. */
export default class SiteSettingsPage extends React.Component<Record<string, never>, SiteSettingsState> {
  public state: SiteSettingsState = {
    data: null, message: '', footer: { footer_brand: '', footer_tagline: '', footer_copyright: '' }, saving: null, error: '', notice: '',
  };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    api.get<AdminSiteSettings>('/admin/site-settings/')
      .then((r) => this.mounted && this.setState({
        data: r.data,
        message: r.data.paused_message,
        footer: { footer_brand: r.data.footer_brand ?? '', footer_tagline: r.data.footer_tagline ?? '', footer_copyright: r.data.footer_copyright ?? '' },
      }))
      .catch((err) => this.mounted && this.setState({ error: errorMessage(err) }));
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private save = async (patch: Partial<AdminSiteSettings>, saving: SiteSettingsState['saving'], notice: string): Promise<void> => {
    this.setState({ saving, error: '', notice: '' });
    try {
      const { data } = await api.patch<AdminSiteSettings>('/admin/site-settings/', patch);
      clearApiCache();  // visitors' cached place data picks up the change
      if (this.mounted) this.setState({ data, notice });
    } catch (err) {
      if (this.mounted) this.setState({ error: errorMessage(err) });
    } finally {
      if (this.mounted) this.setState({ saving: null });
    }
  };

  public render(): React.ReactNode {
    const { data, message, saving, error, notice } = this.state;
    return (
      <div>
        <h1 className="h2 mb-1">Settings</h1>
        <p className="text-muted mb-4">
          Site-wide booking switches. A place takes a kind of booking only when the switch here <strong>and</strong> the place&apos;s own
          switch (Admin &rarr; Places: Individual / Groups) are both on. Ticket-counter sales are never blocked.
        </p>
        {error && <div className="alert alert-danger">{error}</div>}
        {notice && <div className="alert alert-success">{notice}</div>}
        {!data ? (
          <Loader />
        ) : (
          <>
            <div className="card border-0 shadow-sm mb-4">
              <div className="list-group list-group-flush">
                {SWITCHES.map((s) => (
                  <div key={s.key} className="list-group-item d-flex align-items-start gap-3 py-3">
                    <i className={`bi ${s.icon} fs-4 text-primary`} aria-hidden="true" />
                    <div className="flex-grow-1">
                      <label className="fw-semibold d-block" htmlFor={`ss-${s.key}`}>{s.label}</label>
                      <div className="small text-muted">{s.help}</div>
                    </div>
                    <span className={`badge ${data[s.key] ? 'bg-success' : 'bg-secondary'} me-2`}>{data[s.key] ? 'On' : 'Paused'}</span>
                    <div className="form-check form-switch mb-0">
                      <input
                        id={`ss-${s.key}`}
                        className="form-check-input"
                        type="checkbox"
                        role="switch"
                        checked={data[s.key]}
                        disabled={saving !== null}
                        onChange={() => this.save({ [s.key]: !data[s.key] }, s.key, `${s.label} ${data[s.key] ? 'paused' : 'switched on'}.`)}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div className="card border-0 shadow-sm">
              <div className="card-body">
                <label htmlFor="ss-message" className="form-label fw-semibold">Message shown to visitors while something is paused</label>
                <div className="d-flex gap-2">
                  <input id="ss-message" className="form-control" maxLength={200} placeholder="e.g. Group bookings are paused during the festival week."
                    value={message} onChange={(e) => this.setState({ message: e.target.value })} />
                  <button type="button" className="btn btn-primary" disabled={saving !== null || message === data.paused_message}
                    onClick={() => this.save({ paused_message: message }, 'message', 'Message saved.')}>Save</button>
                </div>
                <div className="form-text">Leave empty to use the standard wording (translated into every language).</div>
              </div>
            </div>
            <div className="card border-0 shadow-sm mt-4">
              <div className="card-body">
                <h2 className="h5 mb-1">Footer</h2>
                <p className="small text-muted">Shown at the bottom of every visitor page. Leave a field empty to keep the standard wording.</p>
                {FOOTER_FIELDS.map((f) => (
                  <div className="mb-3" key={f.key}>
                    <label htmlFor={`ss-${f.key}`} className="form-label fw-semibold">{f.label}</label>
                    <input id={`ss-${f.key}`} className="form-control" maxLength={f.key === 'footer_brand' ? 80 : 200} placeholder={f.placeholder}
                      value={this.state.footer[f.key]} onChange={(e) => this.setState({ footer: { ...this.state.footer, [f.key]: e.target.value } })} />
                    <div className="form-text">{f.help}</div>
                  </div>
                ))}
                <div className="d-flex align-items-center gap-3">
                  <button type="button" className="btn btn-primary" disabled={saving !== null}
                    onClick={() => this.save(this.state.footer, 'footer', 'Footer saved. Visitors see it on their next page load.')}>Save footer</button>
                  <span className="small text-muted">
                    Preview: <strong>{(this.state.footer.footer_copyright.trim() || `© {year} ${this.state.footer.footer_brand.trim() || 'Ancient Antiquity'}`).split('{year}').join(String(new Date().getFullYear()))}</strong>
                  </span>
                </div>
              </div>
            </div>
            {data.updated_at && (
              <p className="small text-muted mt-3">Last changed {formatDateTime(data.updated_at)}{data.updated_by_name ? ` by ${data.updated_by_name}` : ''}. Changes are recorded in the audit log.</p>
            )}
          </>
        )}
      </div>
    );
  }
}
