import * as React from 'react';
import { Link, NavLink } from 'react-router-dom';
import { api, errorMessage } from '../../api/client';
import { withAuth, WithAuthProps } from '../../context/AuthContext';
import { withRouter, WithRouterProps } from '../../utils/withRouter';

/*
 * Legal & support pages: Terms of Use, Privacy Policy, Refund & Cancellation Policy and Contact.
 * Routes: /terms, /privacy, /refund-policy, /contact.
 *
 * The company details below are filled in (CIN and GSTIN are SAMPLES until the real ones are available);
 * the whole text must still be reviewed by a lawyer before going live.
 */

const LAST_UPDATED = '22 October 2026';
const COMPANY = 'Ancient Antiquity Heritage Pvt. Ltd.';
const ADDRESS = '11, RS House, SG Highway, Ahmedabad, Gujarat 380054';
const GSTIN = '24ABCDE1234F1Z5'; // SAMPLE - replace with the real GSTIN before go-live
const CIN = 'U79120GJ2026PTC154321'; // SAMPLE - replace with the real CIN from the incorporation certificate
const GRIEVANCE_OFFICER = 'Ruchik Shah, Founder';
const GRIEVANCE_EMAIL = 'grievance@ancientantiquity.in';
const JURISDICTION_CITY = 'Ahmedabad';

// ---------- small shared helpers ----------

export interface SupportInfo {
  email: string;
  phone: string;
}

let supportInfoRequest: Promise<SupportInfo> | null = null;

/** Support email/phone from the API (`SUPPORT_EMAIL`, `SUPPORT_PHONE`); fetched once per page load. */
export function loadSupportInfo(): Promise<SupportInfo> {
  supportInfoRequest ??= api
    .get<SupportInfo>('/support/info/')
    .then((r) => r.data)
    .catch(() => {
      supportInfoRequest = null; // try again next time
      return { email: '', phone: '' };
    });
  return supportInfoRequest;
}

let refundHoursRequest: Promise<number> | null = null;

/** The refund cut-off configured on the server (REFUND_FULL_BEFORE_HOURS, default 24). */
function loadRefundHours(): Promise<number> {
  refundHoursRequest ??= api
    .get<{ refund_full_before_hours?: number }>('/payments/config/')
    .then((r) => r.data.refund_full_before_hours ?? 24)
    .catch(() => {
      refundHoursRequest = null;
      return 24;
    });
  return refundHoursRequest;
}

const LEGAL_NAV = [
  { to: '/terms', label: 'Terms of Use', icon: 'bi-file-earmark-text' },
  { to: '/privacy', label: 'Privacy Policy', icon: 'bi-shield-lock' },
  { to: '/refund-policy', label: 'Refund & Cancellation', icon: 'bi-arrow-counterclockwise' },
  { to: '/contact', label: 'Contact us', icon: 'bi-envelope' },
];

interface LegalShellProps {
  title: string;
  intro?: React.ReactNode;
  /** Legal pages show the "template" notice and the last-updated date; the Contact page does not. */
  legal?: boolean;
  children: React.ReactNode;
}

class LegalShell extends React.Component<LegalShellProps> {
  public componentDidMount(): void {
    document.title = `${this.props.title} · Ancient Antiquity`;
    window.scrollTo(0, 0);
  }

  public render(): React.ReactNode {
    const { title, intro, legal = true, children } = this.props;
    return (
      <div className="container py-4 py-lg-5 page">
        <div className="row g-4">
          <aside className="col-lg-3 order-lg-2">
            <nav className="card border-0 shadow-sm" aria-label="Legal and support pages">
              <div className="list-group list-group-flush">
                {LEGAL_NAV.map((n) => (
                  <NavLink
                    key={n.to}
                    to={n.to}
                    className={({ isActive }) => `list-group-item list-group-item-action${isActive ? ' active' : ''}`}
                  >
                    <i className={`bi ${n.icon} me-2`} aria-hidden="true" />
                    {n.label}
                  </NavLink>
                ))}
              </div>
            </nav>
          </aside>
          <article className="col-lg-9 order-lg-1">
            {legal && (
              <div className="alert alert-warning d-flex gap-2 align-items-start" role="note">
                <i className="bi bi-exclamation-triangle mt-1" aria-hidden="true" />
                <div>
                  <strong>Template — to be reviewed by a lawyer before going live.</strong> Text in [square brackets] must be replaced with
                  the operator's real details.
                </div>
              </div>
            )}
            <h1 className="h2 mb-1">{title}</h1>
            {legal && <p className="text-muted small">Last updated: {LAST_UPDATED}</p>}
            {intro && <div className="lead fs-6 mb-4">{intro}</div>}
            <div className="legal-body">{children}</div>
          </article>
        </div>
      </div>
    );
  }
}

interface SectionProps {
  id: string;
  title: string;
  children: React.ReactNode;
}

class Section extends React.Component<SectionProps> {
  public render(): React.ReactNode {
    const { id, title, children } = this.props;
    return (
      <section id={id} className="mb-4">
        <h2 className="h5 mt-4 mb-2">{title}</h2>
        {children}
      </section>
    );
  }
}

interface SupportLineState {
  info: SupportInfo | null;
}

/** "write to support@… or call …" – used inside legal texts. */
class SupportLine extends React.Component<Record<string, never>, SupportLineState> {
  public state: SupportLineState = { info: null };
  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    loadSupportInfo().then((info) => this.mounted && this.setState({ info }));
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  public render(): React.ReactNode {
    const { info } = this.state;
    const email = info?.email || '[support email]';
    return (
      <>
        <a href={`mailto:${email}`}>{email}</a>
        {info?.phone && (
          <>
            {' '}or call <a href={`tel:${info.phone.replace(/\s+/g, '')}`}>{info.phone}</a>
          </>
        )}
        , or use the <Link to="/contact">contact form</Link>
      </>
    );
  }
}

// ---------- Terms of Use ----------

export class Terms extends React.Component {
  public render(): React.ReactNode {
    return (
      <LegalShell
        title="Terms of Use"
        intro={
          <>
            These terms apply to the Ancient Antiquity website and app (the "Platform"), operated by {COMPANY}, {ADDRESS} ("we", "us"). By
            creating an account or booking a ticket you agree to them. Please also read our <Link to="/privacy">Privacy Policy</Link> and{' '}
            <Link to="/refund-policy">Refund &amp; Cancellation Policy</Link>.
          </>
        }
      >
        <Section id="service" title="1. What we do">
          <p>
            The Platform lets you discover heritage places in India — museums, forts, palaces, monuments and similar sites (each a "Place") —
            and book entry tickets for a date and time slot. Places are run by their own authorities (for example the Archaeological Survey
            of India, state departments, trusts or private owners). We sell tickets on their behalf; each Place's own rules apply on site.
          </p>
        </Section>

        <Section id="account" title="2. Your account">
          <ul>
            <li>You must be at least 18 years old to create an account and pay. Bookings for children must be made by a parent or guardian.</li>
            <li>Give accurate details (name, email, mobile number). Tickets and updates are sent to them.</li>
            <li>Keep your password secret. You are responsible for bookings made from your account. Tell us at once if you suspect misuse.</li>
            <li>We may suspend accounts used for fraud, ticket touting, abuse of staff or breach of these terms.</li>
          </ul>
        </Section>

        <Section id="tickets" title="3. Bookings and tickets">
          <ul>
            <li>A booking is confirmed only after payment succeeds and you receive a ticket with a booking reference and QR code.</li>
            <li>
              Unpaid bookings hold seats for a limited time only. If the hold expires and the slot fills up while you are paying, the booking
              is not confirmed and the amount is refunded automatically in full.
            </li>
            <li>Tickets are valid only for the Place, date and slot shown. Late arrival may mean entry is refused once the slot closes.</li>
            <li>Each QR code admits the listed visitors once. Copies, resale or transfer for profit are not allowed.</li>
            <li>
              Concession tickets (students, children, senior citizens, Indian/SAARC/BIMSTEC nationals, etc.) require valid proof at the gate.
              If proof is not shown you may be asked to pay the difference or be refused entry without refund.
            </li>
            <li>
              At Places managed by the Archaeological Survey of India (ASI), children below 15 years enter free and do not need a paid
              ticket.
            </li>
            <li>Gate staff may check tickets offline; the ticket shown at the gate is authoritative only if it matches our records.</li>
          </ul>
        </Section>

        <Section id="prices" title="4. Prices and payment">
          <ul>
            <li>Prices are in Indian Rupees and include applicable taxes (GST) unless shown otherwise. Tax invoices are issued by {COMPANY} (GSTIN {GSTIN}).</li>
            <li>
              Online payments are processed by Razorpay Software Private Limited. We never see or store your full card, UPI PIN or net-banking
              credentials.
            </li>
            <li>Prices are set by each Place and may change; the price shown when you pay is the price you pay.</li>
            <li>If a price is clearly wrong because of an error, we may cancel the booking and refund you in full.</li>
          </ul>
        </Section>

        <Section id="cancellations" title="5. Cancellations and refunds">
          <p>
            Cancellations and refunds follow our <Link to="/refund-policy">Refund &amp; Cancellation Policy</Link>. Group bookings follow the
            terms of the quote you accepted.
          </p>
        </Section>

        <Section id="visit" title="6. At the Place">
          <ul>
            <li>Follow the Place's rules, staff instructions, security checks and any photography, drone or bag restrictions.</li>
            <li>
              Places may close or restrict areas at short notice (conservation work, VIP visits, weather, law and order). We will tell you
              as soon as we are informed. You can then move your booking to another open date at no charge, or cancel it for a full refund, including any add-ons.
            </li>
            <li>Damaging or defacing a protected monument is an offence under Indian law.</li>
          </ul>
        </Section>

        <Section id="content" title="7. Place information and reviews">
          <p>
            Opening hours, prices, photos and descriptions are provided in good faith but can change. If you spot an error, please{' '}
            <Link to="/contact?topic=data">report incorrect place information</Link>. Reviews must be your own honest experience of a
            visit; we may hide reviews that are abusive, off-topic, promotional or unlawful.
          </p>
        </Section>

        <Section id="use" title="8. Acceptable use">
          <p>
            Do not misuse the Platform: no automated scraping or bulk booking, no attempts to break security, no fake or fraudulent payments,
            and no unlawful, offensive or infringing content. The Platform's design, text, logos and software belong to {COMPANY} or its
            licensors.
          </p>
        </Section>

        <Section id="liability" title="9. Liability">
          <p>
            We are responsible for selling you a valid ticket and for refunds under our policy. We are not responsible for how a Place is
            operated, for events outside our reasonable control, or for indirect losses (such as travel or hotel costs). To the extent the
            law allows, our total liability for a booking is limited to the amount you paid for it. Nothing here limits your rights under
            the Consumer Protection Act, 2019.
          </p>
        </Section>

        <Section id="law" title="10. Governing law and disputes">
          <p>
            These terms are governed by the laws of India. Please contact us first so we can try to resolve any issue. Subject to your
            statutory rights, courts at {JURISDICTION_CITY} have jurisdiction.
          </p>
        </Section>

        <Section id="changes" title="11. Changes and contact">
          <p>
            We may update these terms; the version in force when you book applies to that booking. Questions: <SupportLine />. Company:{' '}
            {COMPANY}, {ADDRESS}, CIN {CIN}.
          </p>
        </Section>
      </LegalShell>
    );
  }
}

// ---------- Privacy Policy ----------

export class Privacy extends React.Component {
  public render(): React.ReactNode {
    return (
      <LegalShell
        title="Privacy Policy"
        intro={
          <>
            This policy explains how {COMPANY} ("we") handles your personal data when you use Ancient Antiquity, in line with the Digital
            Personal Data Protection Act, 2023 (DPDP Act) and the Information Technology Act, 2000. For this data we are the "Data
            Fiduciary".
          </>
        }
      >
        <Section id="collect" title="1. Data we collect">
          <ul>
            <li><strong>Account details:</strong> name, email address, mobile number and a securely hashed password (we never store the password itself).</li>
            <li>
              <strong>Booking details:</strong> Place, date and time slot, number and type of visitors (for example adult, child, student,
              foreign national), amounts paid, booking reference, ticket QR code, check-in time at the gate, and invoice details.
            </li>
            <li>
              <strong>Payment details:</strong> payment status and Razorpay order/payment/refund IDs. Card, UPI and bank credentials are
              handled by Razorpay and never reach us.
            </li>
            <li><strong>Group requests:</strong> organisation name, contact person, group size and visit preferences.</li>
            <li><strong>Messages and reviews:</strong> what you send through the contact form and reviews you post.</li>
            <li>
              <strong>Technical data:</strong> IP address, device and browser type, and server logs, used for security, fraud prevention and
              fixing problems.
            </li>
          </ul>
          <p>We do not ask for Aadhaar numbers or other government ID numbers online. Places may check ID or concession proof at the gate.</p>
        </Section>

        <Section id="purposes" title="2. Why we use it">
          <ul>
            <li>To create and manage your account and sign you in.</li>
            <li>To take payment, issue tickets and tax invoices, and process cancellations and refunds.</li>
            <li>To let Place staff verify tickets at the gate and count visitors.</li>
            <li>To send booking confirmations, reminders and service messages by email, SMS or WhatsApp.</li>
            <li>To answer your questions and complaints.</li>
            <li>To keep the Platform secure, prevent fraud and meet legal, tax and accounting duties.</li>
            <li>With your separate consent only: marketing messages. You can withdraw this consent any time.</li>
          </ul>
          <p>
            We process your data on the basis of your consent given when you register or book, and for legitimate uses allowed by the DPDP
            Act (such as complying with law). You may withdraw consent at any time; this will not affect processing already done, and we
            may then be unable to provide bookings.
          </p>
        </Section>

        <Section id="sharing" title="3. Who we share it with">
          <ul>
            <li><strong>Razorpay</strong> (payment processor) — to process payments and refunds.</li>
            <li>
              <strong>The Place you visit</strong> — the booking reference, visitor count and type, slot and the name on the booking, so
              their staff can admit you and manage capacity.
            </li>
            <li>
              <strong>Service providers</strong> acting on our instructions (Data Processors): cloud hosting in India, our email
              delivery service, SMS and WhatsApp messaging providers, and Razorpay for payments.
            </li>
            <li><strong>Authorities</strong> — when required by law, court order or to protect safety.</li>
          </ul>
          <p>We do not sell your personal data. Your data is stored on servers in India. Some service providers (for example email delivery) may process it outside India under contracts that protect it as Indian law requires.</p>
        </Section>

        <Section id="retention" title="4. How long we keep it">
          <ul>
            <li>Account data: while your account is active, then deleted or anonymised within [90 days] of closure.</li>
            <li>Booking, payment and invoice records: as long as tax and accounting laws require [e.g. 8 years], then deleted.</li>
            <li>Contact messages: [2 years] after the matter is closed.</li>
            <li>Security logs: [180 days], unless needed to investigate an incident.</li>
          </ul>
        </Section>

        <Section id="rights" title="5. Your rights">
          <p>Under the DPDP Act you can:</p>
          <ul>
            <li><strong>Access</strong> — get a summary of your personal data and how we process it.</li>
            <li><strong>Correction and completion</strong> — fix or update your data (most of it directly on your <Link to="/profile">Profile</Link> page).</li>
            <li><strong>Erasure</strong> — ask us to delete your data, except records we must keep by law (such as tax invoices).</li>
            <li><strong>Withdraw consent</strong> — as easily as you gave it.</li>
            <li><strong>Grievance redressal</strong> — complain to our Grievance Officer (below).</li>
            <li><strong>Nominate</strong> a person to exercise your rights in case of death or incapacity.</li>
          </ul>
          <p>
            To use these rights, write to the Grievance Officer or use the <Link to="/contact">contact form</Link> from your registered
            email. We may need to verify your identity. We aim to reply within [30 days].
          </p>
        </Section>

        <Section id="children" title="6. Children">
          <p>
            Accounts are for adults (18+). Children's details are included in a booking only as entered by their parent or guardian, who
            consents on their behalf. We do not track children or show them targeted advertising.
          </p>
        </Section>

        <Section id="storage" title="7. Cookies, local storage and offline data">
          <ul>
            <li>
              <strong>Sign-in tokens</strong> are kept in your browser's local storage so you stay signed in. Signing out removes them.
            </li>
            <li>
              <strong>IndexedDB cache:</strong> public information about places, states, cities and categories is cached on your device so
              pages load fast and work with a weak connection. It contains no personal data.
            </li>
            <li>
              <strong>Service worker cache:</strong> the app shell and place photos are cached for offline use and faster repeat visits.
            </li>
            <li>
              <strong>Offline gate data (staff devices only):</strong> devices used by Place staff for check-in may store that day's ticket
              list (booking reference, visitor count and type, name) so tickets can be checked without internet. It is synced back and
              should be cleared by signing out at the end of the day.
            </li>
            <li>
              <strong>Razorpay</strong> may set its own cookies in the payment window for fraud prevention; see Razorpay's privacy policy.
            </li>
          </ul>
          <p>We do not use advertising or cross-site tracking cookies. We use our own first-party analytics (pages viewed and booking steps) to improve the site; it stays on our servers and is never shared with advertisers.</p>
        </Section>

        <Section id="security" title="8. Security and breaches">
          <p>
            We use HTTPS everywhere, hashed passwords, access controls for staff and regular backups. No system is perfectly secure; if a
            personal data breach occurs we will inform affected users and the Data Protection Board of India as the law requires.
          </p>
        </Section>

        <Section id="grievance" title="9. Grievance Officer">
          <address className="mb-2">
            {GRIEVANCE_OFFICER}, Grievance Officer
            <br />
            {COMPANY}, {ADDRESS}
            <br />
            Email: {GRIEVANCE_EMAIL}
          </address>
          <p>
            We will acknowledge complaints within [48 hours] and try to resolve them within [30 days]. If you are not satisfied, you may
            approach the Data Protection Board of India.
          </p>
        </Section>

        <Section id="changes" title="10. Changes">
          <p>
            We will post changes here and, for important changes, tell you by email. General questions: <SupportLine />.
          </p>
        </Section>
      </LegalShell>
    );
  }
}

// ---------- Refund & Cancellation Policy ----------

interface RefundPolicyState {
  hours: number;
}

export class RefundPolicy extends React.Component<Record<string, never>, RefundPolicyState> {
  public state: RefundPolicyState = { hours: 24 };
  private mounted = false;

  public componentDidMount(): void {
    this.mounted = true;
    loadRefundHours().then((hours) => this.mounted && this.setState({ hours }));
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  public render(): React.ReactNode {
    const { hours } = this.state;
    const cutoff = hours % 24 === 0 && hours >= 48 ? `${hours / 24} days` : `${hours} hours`;
    return (
      <LegalShell
        title="Refund & Cancellation Policy"
        intro={<>In short: cancel at least {cutoff} before your time slot and you get a full refund to the way you paid.</>}
      >
        <div className="row g-3 mb-4">
          <div className="col-md-6">
            <div className="card border-0 shadow-sm h-100 border-start border-success border-4">
              <div className="card-body">
                <div className="fw-semibold text-success mb-1">
                  <i className="bi bi-check-circle me-2" aria-hidden="true" />
                  {cutoff} or more before the slot
                </div>
                Full refund of the amount paid, to the original payment method.
              </div>
            </div>
          </div>
          <div className="col-md-6">
            <div className="card border-0 shadow-sm h-100 border-start border-danger border-4">
              <div className="card-body">
                <div className="fw-semibold text-danger mb-1">
                  <i className="bi bi-x-circle me-2" aria-hidden="true" />
                  Less than {cutoff} before, or no-show
                </div>
                No refund.
              </div>
            </div>
          </div>
        </div>

        <Section id="how" title="1. How to cancel">
          <p>
            Open <Link to="/my-bookings">My Bookings</Link>, open the ticket and select <em>Cancel booking</em>. The app shows whether a refund
            applies before you confirm. A booking is cancelled as a whole; for changes to part of a booking please{' '}
            <Link to="/contact?topic=refund">contact us</Link>.
          </p>
        </Section>

        <Section id="online" title="2. Online bookings">
          <ul>
            <li>
              Cancelled at least <strong>{cutoff}</strong> before the start of your time slot: <strong>full refund</strong> of the amount
              paid, to the original payment method (card, UPI, net banking or wallet).
            </li>
            <li>Cancelled later than that, after the slot has started, or not used (no-show): <strong>no refund</strong>.</li>
            <li>
              Refunds are started immediately through Razorpay. The money usually reaches your account in <strong>5–7 working days</strong>,
              depending on your bank. You receive an email when the refund is processed.
            </li>
            <li>Checked-in (used) tickets cannot be refunded.</li>
          </ul>
        </Section>

        <Section id="automatic" title="3. Automatic refunds">
          <ul>
            <li>
              Unpaid bookings hold your seats for a limited time. If the hold expires and the slot fills up while you are still paying, the
              booking cannot be confirmed and the amount is <strong>refunded automatically in full</strong> — you don't need to do
              anything.
            </li>
            <li>
              If money was debited but no ticket was issued (for example a network failure), the payment is reversed automatically, usually
              within 5–7 working days. If it is not, <Link to="/contact?topic=refund">contact us</Link> with the date, amount and UPI/bank
              reference.
            </li>
          </ul>
        </Section>

        <Section id="counter" title="4. Tickets bought at the counter">
          <p>
            Tickets bought in cash or by card at a Place's ticket counter are refunded <strong>at the counter</strong> of that Place, under
            the same {cutoff} rule. Online refunds are not possible for counter sales.
          </p>
        </Section>

        <Section id="groups" title="5. Group visits">
          <p>
            Group bookings (schools, colleges, tour operators, companies) are confirmed with a written quote. Cancellation and refund terms
            for a group are those stated in its quote.
          </p>
        </Section>

        <Section id="free" title="6. Free entry and concessions">
          <ul>
            <li>
              At Places managed by the Archaeological Survey of India (ASI), <strong>children below 15 years enter free</strong>. Free
              tickets have no charge, so there is nothing to refund.
            </li>
            <li>
              If a concession (student, child, senior citizen, nationality-based price) cannot be proven at the gate, the difference may have
              to be paid on the spot; this is not a reason for a refund.
            </li>
          </ul>
        </Section>

        <Section id="closures" title="7. If a Place closes">
          <p>
            If a Place is closed by its authority on your date (for example a VIP visit, conservation work, government order or severe
            weather), we will inform you and [refund in full / offer a free change of date — confirm with partner Places].
          </p>
        </Section>

        <Section id="help" title="8. Need help?">
          <p>
            For refund questions, write to <SupportLine /> and include your booking reference.
          </p>
        </Section>
      </LegalShell>
    );
  }
}

// ---------- Contact ----------

export const CONTACT_TOPICS = [
  { value: 'booking', label: 'Booking' },
  { value: 'refund', label: 'Refund' },
  { value: 'group', label: 'Group visit' },
  { value: 'data', label: 'Incorrect place information' },
  { value: 'partnership', label: 'Partnership' },
  { value: 'other', label: 'Other' },
];

interface ContactForm {
  name: string;
  email: string;
  phone: string;
  topic: string;
  place_slug: string;
  booking_reference: string;
  message: string;
  website: string; // honeypot – stays empty for humans
}

type ContactProps = WithRouterProps & WithAuthProps;

interface ContactState {
  form: ContactForm;
  info: SupportInfo | null;
  sending: boolean;
  error: string;
  sent: string;
}

class ContactBase extends React.Component<ContactProps, ContactState> {
  private mounted = false;

  public constructor(props: ContactProps) {
    super(props);
    const q = props.router.searchParams;
    const topic = q.get('topic') ?? '';
    this.state = {
      form: {
        name: '',
        email: '',
        phone: '',
        topic: CONTACT_TOPICS.some((t) => t.value === topic) ? topic : 'booking',
        place_slug: (q.get('place') ?? '').slice(0, 220),
        booking_reference: (q.get('booking') ?? '').slice(0, 40),
        message: '',
        website: '',
      },
      info: null,
      sending: false,
      error: '',
      sent: '',
    };
  }

  public componentDidMount(): void {
    this.mounted = true;
    this.prefillFromUser();
    loadSupportInfo().then((info) => this.mounted && this.setState({ info }));
  }

  public componentDidUpdate(prev: ContactProps): void {
    if (!prev.auth.user && this.props.auth.user) this.prefillFromUser();
    if (prev.router.location.search !== this.props.router.location.search) {
      const q = this.props.router.searchParams;
      const topic = q.get('topic') ?? '';
      this.setState((s) => ({
        form: {
          ...s.form,
          topic: CONTACT_TOPICS.some((t) => t.value === topic) ? topic : s.form.topic,
          place_slug: q.get('place') ?? s.form.place_slug,
          booking_reference: q.get('booking') ?? s.form.booking_reference,
        },
      }));
    }
  }

  public componentWillUnmount(): void {
    this.mounted = false;
  }

  private prefillFromUser(): void {
    const u = this.props.auth.user;
    if (!u) return;
    this.setState((s) => ({
      form: {
        ...s.form,
        name: s.form.name || `${u.first_name} ${u.last_name}`.trim(),
        email: s.form.email || u.email,
        phone: s.form.phone || u.phone || '',
      },
    }));
  }

  private set = (field: keyof ContactForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>): void => {
    const value = e.target.value;
    this.setState((s) => ({ form: { ...s.form, [field]: value } }));
  };

  private submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    this.setState({ sending: true, error: '' });
    try {
      const { data } = await api.post<{ detail: string }>('/support/contact/', this.state.form);
      if (this.mounted) this.setState({ sending: false, sent: data.detail });
    } catch (err) {
      const status = (err as { response?: { status?: number } }).response?.status;
      const error =
        status === 429 ? 'You have sent several messages already. Please wait an hour or email us directly.' : errorMessage(err);
      if (this.mounted) this.setState({ sending: false, error });
    }
  };

  private reset = (): void => {
    this.setState((s) => ({ sent: '', form: { ...s.form, message: '', booking_reference: '' } }));
  };

  public render(): React.ReactNode {
    const { form, info, sending, error, sent } = this.state;
    const isData = form.topic === 'data';

    return (
      <LegalShell
        title="Contact us"
        legal={false}
        intro="Questions about a booking, a refund, a group visit or a place's details? Send us a message and we'll reply by email."
      >
        <div className="row g-4">
          <div className="col-md-7">
            <div className="card border-0 shadow-sm">
              <div className="card-body p-4">
                {sent ? (
                  <div className="text-center py-4" role="status">
                    <i className="bi bi-check-circle text-success display-5 d-block mb-3" aria-hidden="true" />
                    <h2 className="h5">Message sent</h2>
                    <p className="text-muted">{sent}</p>
                    <button type="button" className="btn btn-outline-primary" onClick={this.reset}>
                      Send another message
                    </button>
                  </div>
                ) : (
                  <form onSubmit={this.submit}>
                    {error && <div className="alert alert-danger">{error}</div>}
                    <div className="row g-3">
                      <div className="col-sm-6">
                        <label className="form-label" htmlFor="c-name">Name</label>
                        <input id="c-name" className="form-control" required maxLength={120} autoComplete="name" value={form.name} onChange={this.set('name')} />
                      </div>
                      <div className="col-sm-6">
                        <label className="form-label" htmlFor="c-email">Email</label>
                        <input id="c-email" type="email" className="form-control" required autoComplete="email" value={form.email} onChange={this.set('email')} />
                      </div>
                      <div className="col-sm-6">
                        <label className="form-label" htmlFor="c-phone">
                          Phone <span className="text-muted small">(optional)</span>
                        </label>
                        <input id="c-phone" type="tel" className="form-control" maxLength={20} autoComplete="tel" value={form.phone} onChange={this.set('phone')} />
                      </div>
                      <div className="col-sm-6">
                        <label className="form-label" htmlFor="c-topic">Topic</label>
                        <select id="c-topic" className="form-select" value={form.topic} onChange={this.set('topic')}>
                          {CONTACT_TOPICS.map((t) => (
                            <option key={t.value} value={t.value}>{t.label}</option>
                          ))}
                        </select>
                      </div>
                      {(isData || form.place_slug) && (
                        <div className="col-sm-6">
                          <label className="form-label" htmlFor="c-place">
                            Place <span className="text-muted small">(optional)</span>
                          </label>
                          <input id="c-place" className="form-control" maxLength={220} placeholder="e.g. red-fort" value={form.place_slug} onChange={this.set('place_slug')} />
                          {form.place_slug && (
                            <div className="form-text">
                              <Link to={`/museums/${encodeURIComponent(form.place_slug)}`} target="_blank" rel="noopener">View place page</Link>
                            </div>
                          )}
                        </div>
                      )}
                      {(form.topic === 'booking' || form.topic === 'refund' || form.booking_reference) && (
                        <div className="col-sm-6">
                          <label className="form-label" htmlFor="c-ref">
                            Booking reference <span className="text-muted small">(optional)</span>
                          </label>
                          <input id="c-ref" className="form-control" maxLength={40} value={form.booking_reference} onChange={this.set('booking_reference')} />
                        </div>
                      )}
                      <div className="col-12">
                        <label className="form-label" htmlFor="c-message">Message</label>
                        <textarea
                          id="c-message"
                          className="form-control"
                          rows={6}
                          required
                          minLength={10}
                          maxLength={5000}
                          placeholder={
                            isData
                              ? 'What is wrong (opening hours, prices, address, photos, description…) and what is correct? A source link helps.'
                              : 'How can we help?'
                          }
                          value={form.message}
                          onChange={this.set('message')}
                        />
                      </div>
                      {/* Honeypot: hidden from people and screen readers; bots tend to fill it. */}
                      <div className="d-none" aria-hidden="true">
                        <label htmlFor="c-website">Website</label>
                        <input id="c-website" tabIndex={-1} autoComplete="off" value={form.website} onChange={this.set('website')} />
                      </div>
                      <div className="col-12 d-flex justify-content-between align-items-center flex-wrap gap-2">
                        <span className="small text-muted">
                          We use these details only to answer you. See our <Link to="/privacy">Privacy Policy</Link>.
                        </span>
                        <button type="submit" className="btn btn-primary" disabled={sending}>
                          {sending ? <span className="spinner-border spinner-border-sm me-2" aria-hidden="true" /> : <i className="bi bi-envelope me-2" aria-hidden="true" />}
                          Send message
                        </button>
                      </div>
                    </div>
                  </form>
                )}
              </div>
            </div>
          </div>

          <div className="col-md-5">
            <div className="card border-0 shadow-sm mb-3">
              <div className="card-body">
                <h2 className="h6 text-uppercase text-muted mb-3">Customer support</h2>
                {info === null ? (
                  <div className="placeholder-glow">
                    <span className="placeholder col-8" />
                  </div>
                ) : (
                  <ul className="list-unstyled mb-0 d-flex flex-column gap-2">
                    {info.email && (
                      <li>
                        <i className="bi bi-envelope me-2 text-primary" aria-hidden="true" />
                        <a href={`mailto:${info.email}`}>{info.email}</a>
                      </li>
                    )}
                    {info.phone && (
                      <li>
                        <i className="bi bi-telephone me-2 text-primary" aria-hidden="true" />
                        <a href={`tel:${info.phone.replace(/\s+/g, '')}`}>{info.phone}</a>
                      </li>
                    )}
                    <li className="text-muted small">
                      <i className="bi bi-clock me-2" aria-hidden="true" />
                      Mon–Sat, 9:30 am – 6:30 pm IST
                    </li>
                  </ul>
                )}
              </div>
            </div>
            <div className="card border-0 shadow-sm mb-3">
              <div className="card-body small">
                <h2 className="h6 text-uppercase text-muted mb-2">Quick answers</h2>
                <ul className="mb-0 ps-3">
                  <li>Cancel a booking from its ticket in <Link to="/my-bookings">My Bookings</Link>.</li>
                  <li>Refund timings: see the <Link to="/refund-policy">Refund policy</Link> (usually 5–7 working days).</li>
                  <li>Data or privacy requests: see <Link to="/privacy#grievance">Grievance Officer</Link>.</li>
                </ul>
              </div>
            </div>
            <div className="card border-0 shadow-sm">
              <div className="card-body small text-muted">
                <h2 className="h6 text-uppercase mb-2">Registered office</h2>
                {COMPANY}
                <br />
                {ADDRESS}
                <br />
                GSTIN: {GSTIN}
              </div>
            </div>
          </div>
        </div>
      </LegalShell>
    );
  }
}

export const Contact = withRouter(withAuth(ContactBase));
