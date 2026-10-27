import * as React from 'react';
import { Link } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import type { Paginated } from '../../api/types';
import { Empty, Loader, Pagination } from '../../components/Common';
import { formatDateTime } from '../../utils/format';
import { CONTACT_TOPICS } from '../client/Legal';

type MessageStatus = 'new' | 'in_progress' | 'closed';

interface SupportMessage {
  id: number;
  name: string;
  email: string;
  phone: string;
  topic: string;
  topic_label: string;
  place_slug: string;
  booking_reference: string;
  message: string;
  status: MessageStatus;
  status_label: string;
  admin_note: string;
  user_email: string | null;
  created_at: string;
  updated_at: string;
}

const STATUSES: { value: MessageStatus; label: string; badge: string }[] = [
  { value: 'new', label: 'New', badge: 'bg-danger' },
  { value: 'in_progress', label: 'In progress', badge: 'bg-warning text-dark' },
  { value: 'closed', label: 'Closed', badge: 'bg-secondary' },
];

interface SupportMessagesState {
  data: Paginated<SupportMessage> | null;
  page: number;
  search: string;
  status: string;
  topic: string;
  error: string;
  notes: Record<number, string>;
}

class SupportMessages extends React.Component<Record<string, never>, SupportMessagesState> {
  public state: SupportMessagesState = { data: null, page: 1, search: '', status: 'new', topic: '', error: '', notes: {} };

  private timer: ReturnType<typeof setTimeout> | undefined;
  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    this.scheduleLoad();
  }

  public componentDidUpdate(_p: Record<string, never>, prev: SupportMessagesState): void {
    const s = this.state;
    if (s.page !== prev.page || s.search !== prev.search || s.status !== prev.status || s.topic !== prev.topic) this.scheduleLoad();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    clearTimeout(this.timer);
  }

  private scheduleLoad(): void {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      const { page, search, status, topic } = this.state;
      api
        .get<Paginated<SupportMessage>>('/admin/support-messages/', {
          params: { page, search: search || undefined, status: status || undefined, topic: topic || undefined },
        })
        .then((r) => this.mounted && this.setState({ data: r.data, error: '' }))
        .catch((err) => this.mounted && this.setState({ data: null, error: errorMessage(err) }));
    }, 250);
  }

  private update = async (m: SupportMessage, patch: Partial<Pick<SupportMessage, 'status' | 'admin_note'>>): Promise<void> => {
    try {
      const { data: updated } = await api.patch<SupportMessage>(`/admin/support-messages/${m.id}/`, patch);
      this.setState((s) => ({ data: s.data && { ...s.data, results: s.data.results.map((x) => (x.id === m.id ? updated : x)) } }));
    } catch (err) {
      this.setState({ error: errorMessage(err) });
    }
  };

  public render(): React.ReactNode {
    const { data, page, search, status, topic, error, notes } = this.state;
    return (
      <div>
        <h1 className="h2 mb-2">Support messages</h1>
        <p className="text-muted mb-4">Messages from the public Contact page. Reply by email, then mark them closed.</p>
        <div className="card border-0 shadow-sm mb-3">
          <div className="card-body">
            <div className="row g-2">
              <div className="col-lg-6">
                <input className="form-control" placeholder="Search name, email, text, place, booking…" value={search} onChange={(e) => this.setState({ search: e.target.value, page: 1 })} />
              </div>
              <div className="col-sm-6 col-lg-3">
                <select className="form-select" value={status} onChange={(e) => this.setState({ status: e.target.value, page: 1 })} aria-label="Status">
                  <option value="">All statuses</option>
                  {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
              </div>
              <div className="col-sm-6 col-lg-3">
                <select className="form-select" value={topic} onChange={(e) => this.setState({ topic: e.target.value, page: 1 })} aria-label="Topic">
                  <option value="">All topics</option>
                  {CONTACT_TOPICS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </div>
            </div>
          </div>
        </div>
        {error && <div className="alert alert-danger">{error}</div>}

        {data === null ? (
          !error && <Loader />
        ) : data.count === 0 ? (
          <Empty title="No messages">Nothing matches these filters.</Empty>
        ) : (
          <>
            <div className="d-flex flex-column gap-3">
              {data.results.map((m) => {
                const st = STATUSES.find((s) => s.value === m.status);
                const note = notes[m.id] ?? m.admin_note;
                return (
                  <div key={m.id} className="card border-0 shadow-sm">
                    <div className="card-body">
                      <div className="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-2">
                        <div className="min-w-0">
                          <span className={`badge ${st?.badge ?? 'bg-secondary'} me-2`}>{m.status_label}</span>
                          <span className="badge bg-light text-dark border me-2">{m.topic_label}</span>
                          <strong>{m.name}</strong>{' '}
                          <a href={`mailto:${m.email}?subject=${encodeURIComponent(`Re: your message (#${m.id})`)}`}>{m.email}</a>
                          {m.phone && <span className="text-muted"> · {m.phone}</span>}
                          <div className="text-muted small">
                            #{m.id} · {formatDateTime(m.created_at)}
                            {m.place_slug && (
                              <> · Place <Link to={`/museums/${m.place_slug}`} target="_blank">{m.place_slug}</Link></>
                            )}
                            {m.booking_reference && <> · Booking <span className="ref">{m.booking_reference}</span></>}
                          </div>
                        </div>
                        <select
                          className="form-select form-select-sm w-auto"
                          value={m.status}
                          onChange={(e) => this.update(m, { status: e.target.value as MessageStatus })}
                          aria-label="Change status"
                        >
                          {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                        </select>
                      </div>
                      <p className="mb-2" style={{ whiteSpace: 'pre-wrap' }}>{m.message}</p>
                      <div className="input-group input-group-sm">
                        <input
                          className="form-control"
                          placeholder="Internal note (not sent to the visitor)"
                          value={note}
                          onChange={(e) => {
                            const value = e.target.value;
                            this.setState((s) => ({ notes: { ...s.notes, [m.id]: value } }));
                          }}
                        />
                        <button className="btn btn-outline-secondary" disabled={note === m.admin_note} onClick={() => this.update(m, { admin_note: note })}>
                          Save note
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="mt-3">
              <Pagination page={page} count={data.count} onChange={(p) => this.setState({ page: p })} />
            </div>
          </>
        )}
      </div>
    );
  }
}

export default SupportMessages;
