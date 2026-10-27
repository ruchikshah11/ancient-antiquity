import { QRCodeSVG } from 'qrcode.react';
import * as React from 'react';
import { api, errorMessage } from '../../api/client';
import type { Availability, Booking, Museum } from '../../api/types';
import { Loader } from '../../components/Common';
import MuseumPicker from '../../components/MuseumPicker';
import { formatDate, formatINR, formatPrice, formatTime, isoDate } from '../../utils/format';
import { gateMuseum } from '../../utils/gateMuseum';

const METHODS = [
  { id: 'cash', label: 'Cash' },
  { id: 'upi', label: 'UPI' },
  { id: 'card', label: 'Card' },
];

interface CounterSaleProps {}

interface CounterSaleState {
  slug: string;
  museum: Museum | null;
  availability: Availability | null;
  slotId: number | null;
  qty: Record<number, number>;
  method: string;
  checkIn: boolean;
  name: string;
  phone: string;
  error: string;
  busy: boolean;
  sold: Booking | null;
  reload: number;
}

class CounterSalePage extends React.Component<CounterSaleProps, CounterSaleState> {
  public state: CounterSaleState = {
    slug: gateMuseum.get(),
    museum: null,
    availability: null,
    slotId: null,
    qty: {},
    method: 'cash',
    checkIn: true,
    name: '',
    phone: '',
    error: '',
    busy: false,
    sold: null,
    reload: 0,
  };

  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    this.loadMuseum();
  }

  public componentDidUpdate(_prevProps: CounterSaleProps, prevState: CounterSaleState): void {
    if (this.state.slug !== prevState.slug) this.loadMuseum();
    if (this.state.museum !== prevState.museum || this.state.reload !== prevState.reload) this.loadAvailability();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private setSlug = (slug: string): void => {
    gateMuseum.set(slug);
    this.setState({ slug });
  };

  private loadMuseum(): void {
    const { slug } = this.state;
    this.setState({ museum: null });
    if (slug)
      api
        .get<Museum>(`/museums/${slug}/`)
        .then((r) => {
          if (this.mounted && this.state.slug === slug) this.setState({ museum: r.data });
        })
        .catch(() => {
          if (this.mounted && this.state.slug === slug) this.setSlug('');
        });
  }

  private loadAvailability(): void {
    const { museum } = this.state;
    if (!museum) return;
    api
      .get<Availability>(`/museums/${museum.slug}/availability/`, { params: { date: isoDate(0), counter: 1 } })
      .then((r) => {
        if (!this.mounted) return;
        // Default to the slot running right now.
        this.setState((s) => ({
          availability: r.data,
          slotId: s.slotId && r.data.slots.some((x) => x.id === s.slotId && x.bookable) ? s.slotId : r.data.slots.find((x) => x.bookable)?.id ?? null,
        }));
      });
  }

  private getTickets(): NonNullable<Museum['ticket_types']> {
    return (this.state.museum?.ticket_types ?? []).filter((t) => t.is_active);
  }

  private sell = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { museum, slotId, qty, method, checkIn, name, phone } = this.state;
    const tickets = this.getTickets();
    this.setState({ busy: true, error: '' });
    try {
      const { data } = await api.post<Booking>('/bookings/counter/', {
        museum: museum!.slug,
        slot: slotId,
        items: tickets.map((t) => ({ ticket_type: t.id, quantity: qty[t.id!] ?? 0 })).filter((i) => i.quantity > 0),
        payment_method: method,
        check_in: checkIn,
        visitor_name: name || undefined,
        visitor_phone: phone,
      });
      this.setState((s) => ({ sold: data, qty: {}, name: '', phone: '', reload: s.reload + 1 }));
    } catch (err) {
      this.setState((s) => ({ error: errorMessage(err), reload: s.reload + 1 }));
    } finally {
      this.setState({ busy: false });
    }
  };

  public render(): React.ReactNode {
    const { slug, museum, availability, slotId, qty, method, checkIn, name, phone, error, busy, sold } = this.state;
    const tickets = this.getTickets();
    const count = Object.values(qty).reduce((a, b) => a + b, 0);
    const total = tickets.reduce((sum, t) => sum + Number(t.price) * (qty[t.id!] ?? 0), 0);
    const slot = availability?.slots.find((s) => s.id === slotId);

    return (
      <div>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-4 no-print">
          <h1 className="h2 mb-0">Ticket counter</h1>
          <span className="text-muted small">Walk-in sales for today · {formatDate(isoDate(0), { weekday: 'long', day: 'numeric', month: 'long' })}</span>
        </div>

        <div className="card border-0 shadow-sm mb-4 no-print" style={{ maxWidth: 520 }}>
          <div className="card-body">
            <MuseumPicker value={slug} onChange={(s) => { this.setSlug(s); this.setState({ sold: null }); }} />
          </div>
        </div>

        {slug && !museum && <Loader />}

        {museum && (
          <div className="row g-4">
            <div className="col-lg-7 no-print">
              <form className="card border-0 shadow-sm" onSubmit={this.sell}>
                <div className="card-body">
                  {error && <div className="alert alert-danger">{error}</div>}
                  {availability?.closed && <div className="alert alert-warning">{museum.name} is closed today.</div>}

                  <div className="mb-4">
                    <label className="form-label fw-semibold">Entry slot</label>
                    {!availability ? (
                      <Loader />
                    ) : (
                      <div className="row g-2">
                        {availability.slots.map((s) => (
                          <div className="col-6 col-sm-4" key={s.id}>
                            <button type="button" className={`btn slot-btn w-100 ${slotId === s.id ? 'btn-primary' : 'btn-outline-primary'}`} disabled={!s.bookable} onClick={() => this.setState({ slotId: s.id })}>
                              <strong>{formatTime(s.start_time)} – {formatTime(s.end_time)}</strong>
                              <small className={s.available > 0 && s.available <= 10 && slotId !== s.id ? 'text-danger' : ''}>
                                {s.available === 0 ? 'Full' : !s.bookable ? 'Ended' : `${s.available} left`}
                              </small>
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <ul className="list-group list-group-flush mb-4">
                    {tickets.map((t) => (
                      <li key={t.id} className="list-group-item d-flex justify-content-between align-items-center gap-3 px-0">
                        <div>
                          <div className="fw-semibold">{t.name}</div>
                          <div className="text-muted small">{formatPrice(t.price)}</div>
                        </div>
                        <div className="input-group input-group-sm" style={{ width: 120 }}>
                          <button type="button" className="btn btn-outline-primary" aria-label={`Fewer ${t.name}`} disabled={!qty[t.id!]} onClick={() => this.setState({ qty: { ...qty, [t.id!]: (qty[t.id!] ?? 0) - 1 } })}>
                            <i className="bi bi-dash-lg" aria-hidden="true" />
                          </button>
                          <span className="form-control text-center fw-semibold">{qty[t.id!] ?? 0}</span>
                          <button type="button" className="btn btn-outline-primary" aria-label={`More ${t.name}`} disabled={count >= Math.min(20, slot?.available ?? 0)} onClick={() => this.setState({ qty: { ...qty, [t.id!]: (qty[t.id!] ?? 0) + 1 } })}>
                            <i className="bi bi-plus-lg" aria-hidden="true" />
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>

                  <div className="row g-3 mb-3">
                    <div className="col-md-6">
                      <label htmlFor="c-name" className="form-label">Visitor name (optional)</label>
                      <input id="c-name" className="form-control" value={name} onChange={(e) => this.setState({ name: e.target.value })} placeholder="Walk-in visitor" />
                    </div>
                    <div className="col-md-6">
                      <label htmlFor="c-phone" className="form-label">Mobile (optional)</label>
                      <input id="c-phone" className="form-control" inputMode="tel" value={phone} onChange={(e) => this.setState({ phone: e.target.value })} />
                    </div>
                  </div>

                  <div className="mb-3">
                    <label className="form-label d-block">Payment received by</label>
                    <div className="btn-group" role="group" aria-label="Payment method">
                      {METHODS.map((m) => (
                        <button type="button" key={m.id} className={`btn btn-outline-primary ${method === m.id ? 'active' : ''}`} aria-pressed={method === m.id} onClick={() => this.setState({ method: m.id })}>
                          {m.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="form-check mb-3">
                    <input id="c-checkin" className="form-check-input" type="checkbox" checked={checkIn} onChange={(e) => this.setState({ checkIn: e.target.checked })} />
                    <label htmlFor="c-checkin" className="form-check-label">Visitor enters now (mark as checked in)</label>
                  </div>

                  <div className="d-flex justify-content-between align-items-center border-top pt-3 mb-3 fs-5 fw-bold">
                    <span>{count} ticket{count === 1 ? '' : 's'}</span>
                    <span>{formatINR(total)}</span>
                  </div>
                  <button className="btn btn-accent btn-lg w-100" disabled={busy || !slotId || count === 0}>
                    {busy ? 'Issuing…' : total === 0 ? 'Issue free tickets' : `Collect ${formatINR(total)} & issue ticket`}
                  </button>
                </div>
              </form>
            </div>

            <div className="col-lg-5">
              {sold ? (
                <div className="card border-0 shadow-sm text-center">
                  <div className="card-body d-flex flex-column gap-2">
                    <div className="alert alert-success text-start no-print">
                      <i className="bi bi-check-circle-fill me-2" aria-hidden="true" />
                      Sold. {sold.status === 'checked_in' ? 'Visitor checked in.' : 'Ticket valid for entry today.'}
                    </div>
                    <div className="text-muted small">ANCIENT ANTIQUITY · COUNTER TICKET</div>
                    <h2 className="h4 mb-0">{sold.museum_name}</h2>
                    <div>
                      {formatDate(sold.visit_date)} · {formatTime(sold.slot_start)} – {formatTime(sold.slot_end)}
                    </div>
                    <div className="d-flex justify-content-center">
                      <div className="bg-white p-2 rounded border">
                        <QRCodeSVG value={sold.reference} size={140} />
                      </div>
                    </div>
                    <div className="ref fs-5">{sold.reference}</div>
                    <div className="small">{sold.items.map((i) => `${i.quantity} × ${i.ticket_name}`).join(', ')}</div>
                    <div className="d-flex justify-content-center gap-3 fs-5 fw-bold">
                      <span>Paid ({sold.payment_method.toUpperCase()})</span>
                      <span>{formatINR(sold.total_amount)}</span>
                    </div>
                    <div className="d-flex justify-content-center flex-wrap gap-2 no-print">
                      <button className="btn btn-accent" onClick={() => window.print()}>
                        <i className="bi bi-printer me-1" aria-hidden="true" /> Print ticket
                      </button>
                      <button className="btn btn-outline-primary" onClick={() => this.setState({ sold: null })}>Next visitor</button>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="card border-0 bg-light no-print">
                  <div className="card-body text-muted">
                    <i className="bi bi-printer me-2" aria-hidden="true" />
                    The printed ticket appears here after each sale. Counter and online sales share the same slot capacity, so a
                    slot can never be oversold.
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    );
  }
}

export default CounterSalePage;
