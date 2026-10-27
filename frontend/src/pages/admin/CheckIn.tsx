import { AxiosError } from 'axios';
import * as React from 'react';
import { api, errorMessage } from '../../api/client';
import type { Booking, NeedsCount } from '../../api/types';
import type { GateManifestWithPasses as GateManifest, GateOption, PassCheckin, PassManifestTicket as ManifestTicket } from '../../api/passes';
import MuseumPicker from '../../components/MuseumPicker';
import QrScanner from '../../components/QrScanner';
import { formatDate, formatDateTime, formatTime, isoDate } from '../../utils/format';
import { gateMuseum } from '../../utils/gateMuseum';

/*
 * Gate check-in that keeps working without internet.
 * - While online, every scan is verified by the server (and mirrored into the local list).
 * - The day's ticket list is kept on this device; if the network drops, scans are verified
 *   against it and queued, then uploaded automatically when the connection returns.
 * - Group tickets (one QR for the whole group) ask how many people are entering now, so a
 *   group can come in batches; latecomers scan the same ticket again until nobody is left.
 * - Combo passes (AP- references) admit the whole party once at each included place; the day's
 *   valid passes are part of the offline list.
 * - Places with several entrances: choose the gate (remembered on this device per place) and
 *   every scan records it, for live occupancy per gate.
 */

/** One scan waiting to be uploaded. `arrived` = people admitted by this scan (groups); `scan_id` makes retries safe. */
type QueueEntry = { museum: string; reference: string; checked_in_at: string; arrived?: number; scan_id?: string; gate?: number };
type SyncIssue = { reference: string; detail: string };
type GroupInfo = { arrived: number; remaining: number; total: number; organisation: string; label: string };
type PassInfo = { name: string; used?: number; total?: number; validUntil?: string };
type Result =
  | { ok: true; offline: boolean; reference: string; name: string; visitors: number; slot: string; items: string; group?: GroupInfo; pass?: PassInfo }
  | { ok: false; message: string };
/** A group ticket waiting for the head count. */
type GroupPrompt = {
  reference: string;
  offline: boolean;
  name: string;
  organisation: string;
  label: string;
  remaining: number;
  total: number;
  slot: string;
  items: string;
};

const QUEUE_KEY = 'aa_gate_queue';
const CAMERA_KEY = 'aa_gate_camera';
/** The same ticket seen again by the camera within this time is ignored (it's still being held up). */
const SCAN_COOLDOWN_MS = 4000;
/** In camera mode the result clears itself so the screen is ready for the next visitor. */
const CAMERA_RESULT_MS = 4000;
/** Booking (AA-) and combo pass (AP-) references. */
const REFERENCE_RE = /A[AP]-[A-Z0-9]{8}/;
const manifestKey = (slug: string, date: string) => `aa_gate_${slug}_${date}`;
/** The gate this device stands at, per place. */
const gateKey = (slug: string) => `aa_gate_gate_${slug}`;

function loadGateChoice(slug: string): number | null {
  if (!slug) return null;
  try {
    const raw = localStorage.getItem(gateKey(slug));
    return raw ? Number(raw) || null : null;
  } catch {
    return null;
  }
}
function saveGateChoice(slug: string, gate: number | null): void {
  try {
    if (gate) localStorage.setItem(gateKey(slug), String(gate));
    else localStorage.removeItem(gateKey(slug));
  } catch {
    /* storage blocked: the choice just isn't remembered */
  }
}

function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}
function save(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage full or blocked: offline mode just won't persist */
  }
}

/** Unique id per scan, so re-sending the same offline scan never admits people twice. */
function newScanId(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  } catch {
    /* insecure context: fall through */
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/** People already inside on a manifest ticket (older saved lists may lack visitors_arrived). */
const arrivedOf = (t: ManifestTicket): number =>
  t.is_group ? t.visitors_arrived ?? 0 : t.status === 'checked_in' ? t.total_visitors : 0;

/** Ticket lines plus any add-ons, so the gate sees e.g. "2 × Adult, 1 × Child + 1 × Audio guide". */
const bookingItems = (b: Booking): string =>
  [b.items.map((i) => `${i.quantity} × ${i.ticket_name}`).join(', '), b.addons_summary].filter(Boolean).join(' + ');

const isNetworkError = (err: unknown) => !(err as AxiosError)?.response;
const isNeedsCount = (d: Booking | NeedsCount | PassCheckin): d is NeedsCount => (d as NeedsCount).needs_count === true;
const isPassCheckin = (d: Booking | NeedsCount | PassCheckin): d is PassCheckin => (d as PassCheckin).kind === 'pass';

interface CheckInProps {}

interface CheckInState {
  slug: string;
  manifest: GateManifest | null;
  queue: QueueEntry[];
  online: boolean;
  issues: SyncIssue[];
  reference: string;
  result: Result | null;
  busy: boolean;
  syncing: boolean;
  prompt: GroupPrompt | null;
  count: string;
  countError: string;
  /** Camera scanning switched on (remembered on this device). */
  camera: boolean;
  cameraError: string;
  /** Gate this device stands at (null = not specified). */
  gate: number | null;
}

function loadCameraChoice(): boolean {
  try {
    return localStorage.getItem(CAMERA_KEY) === '1';
  } catch {
    return false;
  }
}
function saveCameraChoice(on: boolean): void {
  try {
    localStorage.setItem(CAMERA_KEY, on ? '1' : '0');
  } catch {
    /* storage blocked: the choice just isn't remembered */
  }
}

class CheckInPage extends React.Component<CheckInProps, CheckInState> {
  public state: CheckInState = {
    slug: gateMuseum.get(),
    manifest: null,
    queue: load(QUEUE_KEY, []),
    online: navigator.onLine,
    issues: [],
    reference: '',
    result: null,
    busy: false,
    syncing: false,
    prompt: null,
    count: '',
    countError: '',
    camera: loadCameraChoice(),
    cameraError: '',
    gate: loadGateChoice(gateMuseum.get()),
  };

  private inputRef = React.createRef<HTMLInputElement>();
  private countRef = React.createRef<HTMLInputElement>();
  private timer: ReturnType<typeof setInterval> | undefined;
  /** Clears the result alert a few seconds after a camera scan. */
  private clearTimer: ReturnType<typeof setTimeout> | undefined;
  /** Reference -> time it was last accepted from the camera (see SCAN_COOLDOWN_MS). */
  private recentScans = new Map<string, number>();
  /** True while a check-in request is running (instance flag: setState is async). */
  private checking = false;
  private audio: AudioContext | null = null;
  /** The date the current manifest was loaded for; a new day reloads it like a museum change. */
  private loadedDate = '';

  public componentDidMount(): void {
    this.loadManifest();
    // Track connectivity; upload queued scans as soon as we're back online, refresh the list every 5 min.
    window.addEventListener('online', this.goOnline);
    window.addEventListener('offline', this.goOffline);
    this.startSyncTimer();
  }

  public componentDidUpdate(_prevProps: CheckInProps, prevState: CheckInState): void {
    if (this.state.slug !== prevState.slug || isoDate(0) !== this.loadedDate) {
      this.loadManifest();
      // The museum/day changed: sync again and restart the 5-minute refresh, as before.
      this.startSyncTimer();
    }
    // Head-count prompt opened: put the cursor in the number box; closed: back to the scan box.
    if (this.state.prompt && this.state.prompt !== prevState.prompt) {
      this.countRef.current?.focus();
      this.countRef.current?.select();
    } else if (!this.state.prompt && prevState.prompt) {
      // Restart the cooldown so the group ticket still held to the camera doesn't reopen the card at once.
      this.recentScans.set(prevState.prompt.reference, Date.now());
      // (In camera mode don't focus the text box: on phones that would pop up the keyboard.)
      if (!this.state.camera) this.inputRef.current?.focus();
    }
    // Camera mode: beep/vibrate for every outcome, and clear the result after a few seconds.
    if (this.state.camera) {
      const { result, prompt } = this.state;
      if (result && result !== prevState.result) {
        this.feedback(result.ok ? 'ok' : 'error');
        clearTimeout(this.clearTimer);
        this.clearTimer = setTimeout(() => {
          if (this.state.result === result) this.setState({ result: null });
        }, CAMERA_RESULT_MS);
      } else if (prompt && !prevState.prompt) {
        this.feedback('attention');
      }
    }
  }

  public componentWillUnmount(): void {
    window.removeEventListener('online', this.goOnline);
    window.removeEventListener('offline', this.goOffline);
    clearInterval(this.timer);
    clearTimeout(this.clearTimer);
    try {
      this.audio?.close();
    } catch {
      /* ignore */
    }
  }

  /** Short beep (Web Audio) + vibration. Higher tone = admitted, lower = problem, middle = needs input. */
  private feedback(kind: 'ok' | 'error' | 'attention'): void {
    try {
      const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (Ctx) {
        this.audio ??= new Ctx();
        const ac = this.audio;
        if (ac.state === 'suspended') ac.resume().catch(() => undefined);
        const tones = kind === 'ok' ? [1320] : kind === 'error' ? [220, 220] : [880];
        const len = kind === 'error' ? 0.16 : 0.12;
        tones.forEach((freq, i) => {
          const start = ac.currentTime + i * (len + 0.06);
          const osc = ac.createOscillator();
          const gain = ac.createGain();
          osc.type = kind === 'error' ? 'square' : 'sine';
          osc.frequency.value = freq;
          gain.gain.setValueAtTime(0.0001, start);
          gain.gain.exponentialRampToValueAtTime(0.25, start + 0.01);
          gain.gain.exponentialRampToValueAtTime(0.0001, start + len);
          osc.connect(gain).connect(ac.destination);
          osc.start(start);
          osc.stop(start + len + 0.02);
        });
      }
    } catch {
      /* no audio: the alert on screen is enough */
    }
    try {
      navigator.vibrate?.(kind === 'ok' ? 80 : kind === 'error' ? [120, 80, 120] : [60, 60, 60]);
    } catch {
      /* not supported */
    }
  }

  // Load the saved list for this museum, then refresh it if we can.
  private loadManifest(): void {
    const { slug } = this.state;
    const today = isoDate(0);
    this.loadedDate = today;
    this.setState({ manifest: slug ? load<GateManifest | null>(manifestKey(slug, today), null) : null });
    this.download();
  }

  private startSyncTimer(): void {
    clearInterval(this.timer);
    this.sync();
    this.timer = setInterval(() => navigator.onLine && this.sync().then(this.download), 5 * 60 * 1000);
  }

  private goOnline = (): void => {
    this.setState({ online: true });
    this.sync().then(this.download);
  };

  private goOffline = (): void => {
    this.setState({ online: false });
  };

  private updateManifest = (m: GateManifest): void => {
    this.setState({ manifest: m });
    save(manifestKey(m.museum, m.date), m);
    // A remembered gate that was removed or closed is forgotten.
    const { gate } = this.state;
    if (gate && m.museum === this.state.slug && m.gates && !m.gates.some((g) => g.id === gate)) {
      saveGateChoice(m.museum, null);
      this.setState({ gate: null });
    }
  };

  private updateQueue = (q: QueueEntry[]): void => {
    this.setState({ queue: q });
    save(QUEUE_KEY, q);
  };

  private download = async (): Promise<void> => {
    const { slug } = this.state;
    const today = isoDate(0);
    if (!slug) return;
    try {
      const { data } = await api.get<GateManifest>('/bookings/gate-manifest/', { params: { museum: slug, date: today } });
      // Keep check-ins made offline that the server doesn't know about yet.
      const queued = load<QueueEntry[]>(QUEUE_KEY, []).filter((q) => q.museum === data.museum);
      const pending = new Set(queued.map((q) => q.reference));
      data.tickets = data.tickets.map((t) => {
        if (!pending.has(t.reference)) return t;
        if (t.is_group) {
          const extra = queued.filter((q) => q.reference === t.reference).reduce((n, q) => n + (q.arrived ?? 0), 0);
          return {
            ...t,
            status: 'checked_in',
            checked_in_at: t.checked_in_at ?? new Date().toISOString(),
            visitors_arrived: Math.min(t.total_visitors, (t.visitors_arrived ?? 0) + extra),
          };
        }
        return t.status !== 'checked_in'
          ? { ...t, status: 'checked_in', checked_in_at: new Date().toISOString(), visitors_arrived: t.total_visitors }
          : t;
      });
      this.updateManifest(data);
      this.setState({ online: true });
    } catch (err) {
      if (isNetworkError(err)) this.setState({ online: false });
    }
  };

  private sync = async (): Promise<void> => {
    const all = load<QueueEntry[]>(QUEUE_KEY, []);
    if (all.length === 0) return;
    this.setState({ syncing: true });
    const byMuseum = all.reduce<Record<string, QueueEntry[]>>((acc, e) => ((acc[e.museum] ??= []).push(e), acc), {});
    let remaining = all;
    const found: SyncIssue[] = [];
    for (const [museum, entries] of Object.entries(byMuseum)) {
      try {
        const { data } = await api.post<{ results: { reference: string; result: string; detail: string }[] }>('/bookings/checkin-sync/', {
          museum,
          entries: entries.map(({ reference: r, checked_in_at, arrived, scan_id, gate }) => ({ reference: r, checked_in_at, arrived, scan_id, gate })),
        });
        const done = new Set(data.results.map((r) => r.reference));
        remaining = remaining.filter((e) => !(e.museum === museum && done.has(e.reference)));
        data.results.filter((r) => r.result !== 'ok').forEach((r) => found.push({ reference: r.reference, detail: r.detail }));
        this.setState({ online: true });
      } catch (err) {
        if (isNetworkError(err)) this.setState({ online: false });
        break;
      }
    }
    this.updateQueue(remaining);
    if (found.length) this.setState((s) => ({ issues: [...found, ...s.issues] }));
    this.setState({ syncing: false });
  };

  /** Mirror a check-in into the local list. `arrived` = total now inside (groups); individuals are all in. */
  private markLocal(ref: string, arrived?: number): void {
    const { manifest } = this.state;
    if (!manifest) return;
    const now = new Date().toISOString();
    this.updateManifest({
      ...manifest,
      tickets: manifest.tickets.map((t) => {
        if (t.reference !== ref) return t;
        return t.is_group
          ? { ...t, status: 'checked_in', checked_in_at: t.checked_in_at ?? now, visitors_arrived: Math.min(t.total_visitors, arrived ?? t.total_visitors) }
          : { ...t, status: 'checked_in', checked_in_at: now, visitors_arrived: t.total_visitors };
      }),
    });
  }

  /** Finds a ticket in today's offline list, or explains why it can't be verified offline. */
  private findOffline(ref: string): ManifestTicket | string {
    const { manifest } = this.state;
    if (!manifest || manifest.date !== isoDate(0)) {
      return "No internet and today's ticket list isn't on this device. Download it when you're back online.";
    }
    return (
      manifest.tickets.find((x) => x.reference === ref) ??
      'Not in the offline list (it may have been booked after the last download). Verify once the internet is back.'
    );
  }

  /** Verify a scan against the local list (no internet). Groups open the head-count prompt. */
  private checkOffline(ref: string): void {
    const t = this.findOffline(ref);
    if (typeof t === 'string') {
      this.setState({ result: { ok: false, message: t }, prompt: null });
      return;
    }
    if (t.is_group) {
      const remaining = t.total_visitors - arrivedOf(t);
      if (remaining <= 0) {
        this.setState({ result: { ok: false, message: 'Everyone on this ticket has already entered.' }, prompt: null });
        return;
      }
      this.setState({
        result: null,
        count: String(remaining),
        countError: '',
        prompt: {
          reference: ref, offline: true, name: t.visitor_name, organisation: t.organisation_name, label: 'Group',
          remaining, total: t.total_visitors, slot: formatTime(t.slot_start), items: t.items,
        },
      });
      return;
    }
    if (t.status === 'checked_in') {
      const what = t.is_pass ? 'This pass was already used here' : 'Already checked in';
      this.setState({ result: { ok: false, message: `${what}${t.checked_in_at ? ` at ${formatDateTime(t.checked_in_at)}` : ''}.` }, prompt: null });
      return;
    }
    const { manifest, queue, gate } = this.state;
    this.markLocal(ref);
    this.updateQueue([
      ...queue,
      { museum: manifest!.museum, reference: ref, checked_in_at: new Date().toISOString(), scan_id: newScanId(), gate: gate ?? undefined },
    ]);
    this.setState({
      prompt: null,
      result: {
        ok: true, offline: true, reference: ref, name: t.visitor_name, visitors: t.total_visitors,
        slot: t.is_pass ? '' : formatTime(t.slot_start), items: t.items,
        pass: t.is_pass ? { name: t.pass_name ?? 'Combo pass', validUntil: t.valid_until } : undefined,
      },
    });
  }

  /** Admit part (or all) of a group using the local list, and queue the scan for upload. */
  private admitOffline(p: GroupPrompt, n: number): void {
    const t = this.findOffline(p.reference);
    if (typeof t === 'string') {
      this.setState({ result: { ok: false, message: t }, prompt: null });
      return;
    }
    const already = arrivedOf(t);
    const remaining = t.total_visitors - already;
    if (remaining <= 0) {
      this.setState({ result: { ok: false, message: 'Everyone on this ticket has already entered.' }, prompt: null });
      return;
    }
    if (n > remaining) {
      this.setState({ countError: `Only ${remaining} of ${t.total_visitors} are still to enter.`, prompt: { ...p, offline: true, remaining } });
      return;
    }
    const { manifest, queue, gate } = this.state;
    this.markLocal(p.reference, already + n);
    this.updateQueue([
      ...queue,
      { museum: manifest!.museum, reference: p.reference, checked_in_at: new Date().toISOString(), arrived: n, scan_id: newScanId(), gate: gate ?? undefined },
    ]);
    this.setState({
      prompt: null,
      result: {
        ok: true, offline: true, reference: p.reference, name: t.visitor_name, visitors: n, slot: formatTime(t.slot_start), items: t.items,
        group: { arrived: already + n, remaining: remaining - n, total: t.total_visitors, organisation: t.organisation_name, label: p.label },
      },
    });
  }

  /** Typed reference / USB scanner (it types the code and presses Enter). */
  private submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const ref = this.state.reference.trim().toUpperCase();
    if (!ref || this.checking) return;
    await this.checkInReference(ref);
    // Back to the scan box, unless a group head-count card took the focus.
    this.setState({ reference: '' }, () => {
      if (!this.state.prompt) this.inputRef.current?.focus();
    });
  };

  /** A QR read by the camera: pull out the reference, skip repeats of the same ticket, then check in. */
  private onCameraDetect = (text: string): void => {
    if (this.checking || this.state.busy || this.state.prompt) return;
    const raw = text.trim().toUpperCase();
    if (!raw) return;
    const ref = raw.match(REFERENCE_RE)?.[0] ?? '';
    const key = ref || raw;
    const now = Date.now();
    this.recentScans.forEach((t, k) => now - t >= SCAN_COOLDOWN_MS && this.recentScans.delete(k));
    if (this.recentScans.has(key)) return;
    this.recentScans.set(key, now);
    if (!ref) {
      this.setState({ prompt: null, result: { ok: false, message: "This QR code isn't an Ancient Antiquity ticket." } });
      return;
    }
    this.checkInReference(ref);
  };

  private onCameraError = (message: string): void => {
    saveCameraChoice(false);
    this.setState({ camera: false, cameraError: message });
  };

  private toggleCamera = (): void => {
    const camera = !this.state.camera;
    saveCameraChoice(camera);
    this.recentScans.clear();
    this.setState({ camera, cameraError: '' });
    // Create/unlock the audio context inside this click, so later beeps are allowed (iOS/Safari).
    try {
      const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (camera && Ctx) {
        this.audio ??= new Ctx();
        if (this.audio.state === 'suspended') this.audio.resume().catch(() => undefined);
      }
    } catch {
      /* no audio */
    }
  };

  /** Check in one reference: online with the server, falling back to the offline list; groups open the head-count card. */
  private async checkInReference(ref: string): Promise<void> {
    const { slug, gate } = this.state;
    if (!ref || this.checking) return;
    this.checking = true;
    this.setState({ busy: true });
    try {
      if (!navigator.onLine) {
        this.setState({ online: false });
        this.checkOffline(ref);
      } else {
        try {
          const { data } = await api.post<Booking | NeedsCount | PassCheckin>('/bookings/checkin/', { reference: ref, museum: slug, gate: gate ?? undefined });
          if (isPassCheckin(data)) {
            this.markLocal(ref);
            this.setState({
              online: true,
              prompt: null,
              result: {
                ok: true, offline: false, reference: ref, name: data.visitor_name, visitors: data.total_visitors, slot: '',
                items: data.items.map((i) => `${i.quantity} × ${i.ticket_name}`).join(', '),
                pass: { name: data.pass_name, used: data.sites_used, total: data.sites_total, validUntil: data.valid_until },
              },
            });
          } else if (isNeedsCount(data)) {
            const b = data.booking;
            this.setState({
              online: true,
              result: null,
              count: String(b.remaining_to_enter),
              countError: '',
              prompt: {
                reference: ref, offline: false, name: b.visitor_name, organisation: b.organisation_name,
                label: b.group_type_label || 'Group', remaining: b.remaining_to_enter, total: b.total_visitors,
                slot: formatTime(b.slot_start), items: bookingItems(b),
              },
            });
          } else {
            this.markLocal(ref);
            this.setState({
              online: true,
              prompt: null,
              result: {
                ok: true, offline: false, reference: ref, name: data.visitor_name, visitors: data.total_visitors,
                slot: formatTime(data.slot_start), items: bookingItems(data),
              },
            });
          }
        } catch (err) {
          if (isNetworkError(err)) {
            this.setState({ online: false });
            this.checkOffline(ref);
          } else {
            this.setState({ prompt: null, result: { ok: false, message: errorMessage(err) } });
          }
        }
      }
    } finally {
      this.checking = false;
      this.setState({ busy: false });
    }
  }

  /** Second step for a group: admit the number of people entering now. */
  private admit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const { prompt, slug, gate } = this.state;
    if (!prompt) return;
    const n = Number(this.state.count);
    if (!Number.isInteger(n) || n < 1 || n > prompt.remaining) {
      this.setState({ countError: `Enter a number from 1 to ${prompt.remaining}.` });
      this.countRef.current?.focus();
      return;
    }
    if (prompt.offline || !navigator.onLine) {
      this.admitOffline(prompt, n);
      return;
    }
    this.setState({ busy: true });
    try {
      const { data } = await api.post<Booking | NeedsCount>('/bookings/checkin/', { reference: prompt.reference, museum: slug, arrived: n, gate: gate ?? undefined });
      const b = isNeedsCount(data) ? data.booking : data;
      this.markLocal(prompt.reference, b.visitors_arrived);
      this.setState({
        online: true,
        prompt: null,
        result: {
          ok: true, offline: false, reference: prompt.reference, name: b.visitor_name, visitors: n, slot: formatTime(b.slot_start),
          items: bookingItems(b),
          group: {
            arrived: b.visitors_arrived, remaining: b.remaining_to_enter, total: b.total_visitors,
            organisation: b.organisation_name, label: b.group_type_label || prompt.label,
          },
        },
      });
    } catch (err) {
      if (isNetworkError(err)) {
        this.setState({ online: false });
        this.admitOffline(prompt, n);
      } else {
        // Usually the count no longer fits (someone else scanned meanwhile): keep the prompt open.
        this.setState({ countError: errorMessage(err) });
        this.countRef.current?.focus();
      }
    } finally {
      this.setState({ busy: false });
    }
  };

  private cancelPrompt = (): void => {
    this.setState({ prompt: null, count: '', countError: '' });
  };

  private onCountKeyDown = (e: React.KeyboardEvent<HTMLInputElement>): void => {
    if (e.key === 'Escape') this.cancelPrompt();
  };

  private onMuseumChange = (s: string): void => {
    gateMuseum.set(s);
    this.setState({ slug: s, result: null, prompt: null, gate: loadGateChoice(s) });
  };

  private onGateChange = (e: React.ChangeEvent<HTMLSelectElement>): void => {
    const gate = Number(e.target.value) || null;
    saveGateChoice(this.state.slug, gate);
    this.setState({ gate });
  };

  private renderGatePicker(gates: GateOption[]): React.ReactNode {
    const { gate } = this.state;
    return (
      <div className="mt-3">
        <label htmlFor="gate-select" className="form-label">Gate</label>
        <select id="gate-select" className="form-select" value={gate ?? ''} onChange={this.onGateChange}>
          <option value="">Not specified</option>
          {gates.map((g) => (
            <option key={g.id} value={g.id}>{g.name}</option>
          ))}
        </select>
        <div className="form-text">Remembered on this device. Every scan records the gate for live occupancy.</div>
      </div>
    );
  }

  private onDownloadClick = (): void => {
    this.download();
  };

  private onSyncClick = (): void => {
    this.sync();
  };

  private renderPrompt(p: GroupPrompt): React.ReactNode {
    const { count, countError, busy } = this.state;
    return (
      <form className="card shadow-sm border-accent mb-4" onSubmit={this.admit} aria-labelledby="group-prompt-title">
        <div className="card-body">
          <div className="d-flex gap-3 align-items-start mb-3">
            <i className="bi bi-people-fill fs-1 text-accent" aria-hidden="true" />
            <div className="min-w-0">
              <div id="group-prompt-title" className="fs-4 fw-bold">
                Group: {p.organisation || p.name} · {p.label}
              </div>
              <div className="fs-5">
                <strong>{p.remaining}</strong> of {p.total} still to enter
              </div>
              <div className="small text-muted">
                <span className="ref">{p.reference}</span> · {p.name} · slot {p.slot}
                {p.offline && <> · checking offline</>}
              </div>
              <div className="small text-muted">{p.items}</div>
            </div>
          </div>
          <label htmlFor="group-count" className="form-label fw-semibold">How many are entering now?</label>
          <div className="d-flex flex-column flex-sm-row gap-2">
            <input
              id="group-count"
              ref={this.countRef}
              type="number"
              inputMode="numeric"
              min={1}
              max={p.remaining}
              step={1}
              className={`form-control form-control-lg ${countError ? 'is-invalid' : ''}`}
              style={{ maxWidth: 200, fontSize: '1.75rem', fontWeight: 700 }}
              value={count}
              onChange={(e) => this.setState({ count: e.target.value, countError: '' })}
              onKeyDown={this.onCountKeyDown}
              aria-describedby="group-count-help"
              required
            />
            <button className="btn btn-accent btn-lg text-nowrap" disabled={busy}>
              <i className="bi bi-door-open me-1" aria-hidden="true" /> {busy ? 'Admitting…' : 'Admit'}
            </button>
            <button type="button" className="btn btn-light btn-lg" onClick={this.cancelPrompt} disabled={busy}>
              Cancel
            </button>
          </div>
          {countError ? (
            <div className="invalid-feedback d-block">{countError}</div>
          ) : (
            <div id="group-count-help" className="form-text">
              1 to {p.remaining}. Latecomers can scan the same ticket again later.
            </div>
          )}
        </div>
      </form>
    );
  }

  public render(): React.ReactNode {
    const { slug, manifest, queue, online, issues, reference, result, busy, syncing, prompt, camera, cameraError, gate } = this.state;
    const gates = manifest?.museum === slug ? manifest?.gates ?? [] : [];
    const gateName = gates.find((g) => g.id === gate)?.name;
    const today = isoDate(0);

    const checkedIn = manifest?.tickets.filter((t) => t.status === 'checked_in') ?? [];
    const expected = manifest?.tickets.reduce((n, t) => n + t.total_visitors, 0) ?? 0;
    const entered = manifest?.tickets.reduce((n, t) => n + arrivedOf(t), 0) ?? 0;
    const stale = manifest && manifest.date !== today;

    return (
      <div style={{ maxWidth: 860 }}>
        <div className="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-4">
          <h1 className="h2 mb-0">Gate check-in</h1>
          <span className={`badge ${online ? 'bg-success' : 'bg-warning'} fs-6`}>
            <i className={`bi ${online ? 'bi-wifi' : 'bi-wifi-off'} me-1`} aria-hidden="true" />
            {online ? 'Online' : 'Offline mode'}
          </span>
        </div>

        <div className="card border-0 shadow-sm mb-4" style={{ maxWidth: 520 }}>
          <div className="card-body">
            <MuseumPicker value={slug} onChange={this.onMuseumChange} />
            {slug && gates.length > 0 && this.renderGatePicker(gates)}
          </div>
        </div>

        {slug && (
          <>
            <div className="row g-3 mb-3">
              <div className="col-sm-4">
                <div className="card border-0 shadow-sm stat-card h-100">
                  <div className="card-body">
                    <div className="d-flex justify-content-between align-items-start">
                      <div className="text-muted small">Tickets today</div>
                      <i className="bi bi-card-checklist text-accent" aria-hidden="true" />
                    </div>
                    <div className="stat-value">{manifest && !stale ? manifest.tickets.length : '—'}</div>
                    <div className="text-muted small">{expected} visitors expected</div>
                  </div>
                </div>
              </div>
              <div className="col-sm-4">
                <div className="card border-0 shadow-sm stat-card h-100">
                  <div className="card-body">
                    <div className="d-flex justify-content-between align-items-start">
                      <div className="text-muted small">Entered</div>
                      <i className="bi bi-door-open text-accent" aria-hidden="true" />
                    </div>
                    <div className="stat-value">{entered}</div>
                    <div className="text-muted small">{checkedIn.length} tickets scanned</div>
                  </div>
                </div>
              </div>
              <div className="col-sm-4">
                <div className="card border-0 shadow-sm stat-card h-100">
                  <div className="card-body">
                    <div className="d-flex justify-content-between align-items-start">
                      <div className="text-muted small">Waiting to sync</div>
                      <i className="bi bi-cloud-arrow-up text-accent" aria-hidden="true" />
                    </div>
                    <div className="stat-value">{queue.length}</div>
                    <div className="text-muted small">{syncing ? 'Syncing…' : queue.length ? 'Uploads when online' : 'All synced'}</div>
                  </div>
                </div>
              </div>
            </div>

            <div className="d-flex align-items-center flex-wrap gap-2 small mb-4">
              <span className="text-muted me-auto">
                {manifest && !stale
                  ? `Offline list: ${manifest.museum_name}, downloaded ${formatDateTime(manifest.generated_at)}`
                  : "Today's offline list hasn't been downloaded yet."}
              </span>
              <button className="btn btn-outline-primary btn-sm" onClick={this.onDownloadClick} disabled={!online}>
                <i className="bi bi-download me-1" aria-hidden="true" /> Download / refresh list
              </button>
              <button className="btn btn-outline-primary btn-sm" onClick={this.onSyncClick} disabled={!queue.length || syncing}>
                <i className="bi bi-arrow-repeat me-1" aria-hidden="true" /> Sync now
              </button>
            </div>

            <form className="card border-0 shadow-sm mb-4" onSubmit={this.submit}>
              <div className="card-body">
                <div className="d-flex align-items-start justify-content-between flex-wrap gap-2 mb-3">
                  <p className="text-muted small mb-0 me-auto" style={{ maxWidth: 420 }}>
                    Scan with the camera, a USB/Bluetooth scanner, or type the reference. Tickets (AA-) and combo passes (AP-) both work.
                    {gateName && <><br /><i className="bi bi-door-open me-1" aria-hidden="true" />Scanning at <strong>{gateName}</strong></>}
                  </p>
                  <button
                    type="button"
                    className={`btn ${camera ? 'btn-primary' : 'btn-outline-primary'} text-nowrap`}
                    onClick={this.toggleCamera}
                    aria-pressed={camera}
                    aria-label={camera ? 'Stop camera scanning' : 'Scan with camera'}
                  >
                    <i className={`bi ${camera ? 'bi-camera-video-off' : 'bi-camera-video'} me-1`} aria-hidden="true" />
                    {camera ? 'Stop camera' : 'Scan with camera'}
                  </button>
                </div>
                {cameraError && (
                  <div className="alert alert-warning d-flex gap-2 align-items-start small" role="alert">
                    <i className="bi bi-camera-video-off fs-5" aria-hidden="true" />
                    <div className="flex-grow-1">{cameraError}</div>
                    <button type="button" className="btn-close" aria-label="Dismiss camera message" onClick={() => this.setState({ cameraError: '' })} />
                  </div>
                )}
                <QrScanner active={camera} paused={!!prompt || busy} onDetect={this.onCameraDetect} onError={this.onCameraError} />
                {camera && (
                  <p className="small text-muted mb-3">
                    <i className="bi bi-volume-up me-1" aria-hidden="true" />
                    A high beep means admitted, a low beep means there's a problem. Results clear after a few seconds.
                  </p>
                )}
                <label htmlFor="ref" className="form-label">Booking or pass reference</label>
                <div className="d-flex flex-column flex-sm-row gap-2">
                  <input id="ref" ref={this.inputRef} className="form-control form-control-lg checkin-input" placeholder="AA-XXXXXXXX or AP-XXXXXXXX" value={reference} onChange={(e) => this.setState({ reference: e.target.value })} autoFocus required autoComplete="off" />
                  <button className="btn btn-accent btn-lg text-nowrap" disabled={busy}>
                    <i className="bi bi-upc-scan me-1" aria-hidden="true" /> {busy ? 'Checking…' : 'Check in'}
                  </button>
                </div>
              </div>
            </form>

            {prompt && this.renderPrompt(prompt)}

            {result?.ok === false && (
              <div className="alert alert-danger d-flex gap-3 align-items-start fs-5" role="alert">
                <i className="bi bi-x-circle-fill fs-3" aria-hidden="true" />
                <div>{result.message}</div>
              </div>
            )}
            {result?.ok && (
              <div className="alert alert-success d-flex gap-3 align-items-start" role="status">
                <i className="bi bi-check-circle-fill fs-1" aria-hidden="true" />
                <div>
                  {result.group ? (
                    <>
                      <div className="fs-4 fw-bold">
                        Admit {result.visitors}
                        {' · '}
                        {result.group.remaining > 0 ? `${result.group.remaining} still to come` : 'everyone is in'}
                      </div>
                      <div>
                        <span className="badge bg-accent me-1">Group</span>
                        {result.group.organisation || result.name} · {result.group.label} · {result.group.arrived}/{result.group.total} entered
                      </div>
                      <div><span className="ref">{result.reference}</span> · {result.name} · slot {result.slot}</div>
                    </>
                  ) : result.pass ? (
                    <>
                      <div className="fs-4 fw-bold">Admit {result.visitors} visitor{result.visitors > 1 ? 's' : ''}</div>
                      <div>
                        <span className="badge bg-primary me-1">Combo pass</span>
                        {result.pass.name}
                        {result.pass.total ? ` · place ${result.pass.used} of ${result.pass.total}` : ''}
                      </div>
                      <div>
                        <span className="ref">{result.reference}</span> · {result.name}
                        {result.pass.validUntil && <> · valid until {formatDate(result.pass.validUntil)}</>}
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="fs-4 fw-bold">Admit {result.visitors} visitor{result.visitors > 1 ? 's' : ''}</div>
                      <div><span className="ref">{result.reference}</span> · {result.name} · slot {result.slot}</div>
                    </>
                  )}
                  <div className="small">{result.items}</div>
                  {result.offline && <div className="small mt-1">Checked offline. It will sync automatically when the internet is back.</div>}
                </div>
              </div>
            )}

            {issues.length > 0 && (
              <div className="card shadow-sm border-warning mb-4">
                <div className="card-header bg-white d-flex justify-content-between align-items-center py-3">
                  <h2 className="h5 mb-0"><i className="bi bi-exclamation-triangle text-warning me-2" aria-hidden="true" />Sync warnings</h2>
                  <button className="btn btn-sm btn-light" onClick={() => this.setState({ issues: [] })}>Clear</button>
                </div>
                <div className="card-body">
                  <p className="text-muted small">These offline entries didn't match the server. Inform the supervisor.</p>
                  <ul className="list-group list-group-flush">
                    {issues.map((i, n) => (
                      <li key={`${i.reference}-${n}`} className="list-group-item d-flex justify-content-between gap-2 px-0">
                        <span className="ref">{i.reference}</span><span className="small">{i.detail}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            {manifest && !stale && manifest.tickets.length > 0 && (
              <details className="card border-0 shadow-sm">
                <summary className="card-header bg-white py-3 fw-semibold" style={{ cursor: 'pointer' }}>
                  Today's ticket list ({formatDate(manifest.date)})
                </summary>
                <div className="table-responsive">
                  <table className="table table-hover align-middle mb-0">
                    <thead className="table-light"><tr><th>Reference</th><th>Visitor</th><th>Slot</th><th className="text-end">People</th><th>Status</th></tr></thead>
                    <tbody>
                      {manifest.tickets.map((t) => {
                        const inside = arrivedOf(t);
                        const partly = t.is_group && inside > 0 && inside < t.total_visitors;
                        return (
                          <tr key={t.reference}>
                            <td className="ref">{t.reference}</td>
                            <td>
                              {t.is_group && <span className="badge bg-accent me-1">Group</span>}
                              {t.is_pass && <span className="badge bg-primary me-1">Pass</span>}
                              {t.visitor_name}
                              {t.is_group && t.organisation_name && <div className="text-muted small">{t.organisation_name}</div>}
                            </td>
                            <td>{t.is_pass ? <span className="small text-muted">{t.pass_name}</span> : formatTime(t.slot_start)}</td>
                            <td className="text-end">{t.is_group ? `${inside}/${t.total_visitors}` : t.total_visitors}</td>
                            <td>
                              {partly ? (
                                <span className="badge bg-warning">Partly in</span>
                              ) : t.status === 'checked_in' ? (
                                <span className="badge bg-success">Entered</span>
                              ) : (
                                <span className="badge bg-light text-dark">Not yet</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </details>
            )}
          </>
        )}
      </div>
    );
  }
}

export default CheckInPage;
