import * as React from 'react';

/*
 * Camera QR scanner.
 * - Uses the browser's native BarcodeDetector when it supports QR codes (fast, hardware assisted),
 *   otherwise decodes frames with jsQR (pure JS, loaded on demand) via an offscreen canvas.
 * - Decodes ~8 frames per second. While `paused` the camera stays on but nothing is decoded.
 * - All camera tracks are stopped when `active` turns false or the component unmounts.
 */

/** Minimal typing for the BarcodeDetector API (not in TypeScript's DOM lib yet). */
interface DetectedBarcode { rawValue: string }
interface BarcodeDetectorLike { detect(source: CanvasImageSource): Promise<DetectedBarcode[]> }
interface BarcodeDetectorCtor {
  new (options?: { formats: string[] }): BarcodeDetectorLike;
  getSupportedFormats?: () => Promise<string[]>;
}
type JsQrFn = typeof import('jsqr').default;

export interface QrScannerProps {
  active: boolean;
  paused: boolean;
  onDetect: (text: string) => void;
  onError?: (message: string) => void;
}

interface QrScannerState {
  status: 'idle' | 'starting' | 'running' | 'error';
  error: string;
  cameras: MediaDeviceInfo[];
  deviceId: string;
}

const SCAN_INTERVAL_MS = 125; // ~8 scans per second
const MAX_DECODE_WIDTH = 640; // downscale big frames for jsQR to keep it fast

/** Turns a getUserMedia failure into a message a gate attendant can act on. */
function cameraErrorMessage(err: unknown): string {
  const name = (err as { name?: string } | null)?.name ?? '';
  switch (name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return 'Camera permission was denied. Allow camera access for this site in the browser settings, then try again.';
    case 'NotFoundError':
    case 'OverconstrainedError':
    case 'DevicesNotFoundError':
      return 'No camera was found on this device. Use a USB/Bluetooth scanner or type the reference.';
    case 'NotReadableError':
    case 'TrackStartError':
    case 'AbortError':
      return 'The camera is busy or could not be started. Close other apps using it and try again.';
    default:
      return `The camera could not be started${(err as Error)?.message ? `: ${(err as Error).message}` : '.'}`;
  }
}

class QrScanner extends React.Component<QrScannerProps, QrScannerState> {
  public state: QrScannerState = { status: 'idle', error: '', cameras: [], deviceId: '' };

  private videoRef = React.createRef<HTMLVideoElement>();
  private stream: MediaStream | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private ctx: CanvasRenderingContext2D | null = null;
  private detector: BarcodeDetectorLike | null = null;
  private jsqr: JsQrFn | null = null;
  private frame = 0;
  private lastScan = 0;
  private decoding = false;
  /** Bumped on every start/stop so a slow getUserMedia from an old start is discarded. */
  private session = 0;
  private unmounted = false;

  public componentDidMount(): void {
    if (this.props.active) this.start();
  }

  public componentDidUpdate(prevProps: QrScannerProps): void {
    if (this.props.active !== prevProps.active) {
      if (this.props.active) this.start();
      else this.stop();
    }
  }

  public componentWillUnmount(): void {
    this.unmounted = true;
    this.stop();
  }

  private fail(message: string): void {
    this.stop();
    if (this.unmounted) return;
    this.setState({ status: 'error', error: message });
    this.props.onError?.(message);
  }

  private async start(): Promise<void> {
    this.stopStream();
    const session = ++this.session;

    if (typeof window !== 'undefined' && !window.isSecureContext) {
      this.fail('The camera only works on a secure connection. Open this page over https (or on this computer via localhost / 127.0.0.1).');
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      this.fail('This browser cannot use the camera. Use a USB/Bluetooth scanner or type the reference.');
      return;
    }

    this.setState({ status: 'starting', error: '' });
    try {
      const { deviceId } = this.state;
      const video: MediaTrackConstraints = deviceId ? { deviceId: { exact: deviceId } } : { facingMode: { ideal: 'environment' } };
      const stream = await navigator.mediaDevices.getUserMedia({ video, audio: false });
      if (session !== this.session || this.unmounted || !this.props.active) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      this.stream = stream;
      await this.prepareDecoder();
      if (session !== this.session) return;

      const el = this.videoRef.current;
      if (el) {
        el.srcObject = stream;
        try {
          await el.play();
        } catch {
          /* autoplay quirks: muted + playsInline normally avoids this; frames still arrive */
        }
      }
      if (session !== this.session) return;
      this.setState({ status: 'running' });
      this.loadCameras(stream);
      this.frame = requestAnimationFrame(this.tick);
    } catch (err) {
      if (session === this.session) this.fail(cameraErrorMessage(err));
    }
  }

  /** Native BarcodeDetector when it can read QR codes, otherwise jsQR (code-split, loaded once). */
  private async prepareDecoder(): Promise<void> {
    if (this.detector || this.jsqr) return;
    try {
      const Ctor = (window as unknown as { BarcodeDetector?: BarcodeDetectorCtor }).BarcodeDetector;
      if (Ctor) {
        const formats = Ctor.getSupportedFormats ? await Ctor.getSupportedFormats() : ['qr_code'];
        if (formats.includes('qr_code')) {
          this.detector = new Ctor({ formats: ['qr_code'] });
          return;
        }
      }
    } catch {
      /* fall back to jsQR */
    }
    const mod = await import('jsqr');
    this.jsqr = mod.default;
  }

  /** Lists the cameras (labels are only available after permission), for the switcher. */
  private async loadCameras(stream: MediaStream): Promise<void> {
    try {
      const all = await navigator.mediaDevices.enumerateDevices();
      const cameras = all.filter((d) => d.kind === 'videoinput');
      const current = stream.getVideoTracks()[0]?.getSettings().deviceId ?? '';
      if (!this.unmounted) this.setState((s) => ({ cameras, deviceId: s.deviceId || current }));
    } catch {
      /* switcher is optional */
    }
  }

  private stopStream(): void {
    cancelAnimationFrame(this.frame);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    const el = this.videoRef.current;
    if (el) el.srcObject = null;
  }

  private stop(): void {
    this.session++;
    this.stopStream();
    if (!this.unmounted && this.state.status !== 'error') this.setState({ status: 'idle' });
  }

  private tick = (now: number): void => {
    if (!this.stream) return;
    this.frame = requestAnimationFrame(this.tick);
    if (this.props.paused || this.decoding || now - this.lastScan < SCAN_INTERVAL_MS) return;
    const el = this.videoRef.current;
    if (!el || el.readyState < 2 || !el.videoWidth) return;
    this.lastScan = now;
    this.decoding = true;
    const session = this.session;
    this.decode(el)
      .then((text) => {
        if (text && session === this.session && !this.props.paused && !this.unmounted) this.props.onDetect(text);
      })
      .catch(() => {
        /* a bad frame: try the next one */
      })
      .finally(() => {
        this.decoding = false;
      });
  };

  private async decode(el: HTMLVideoElement): Promise<string | null> {
    if (this.detector) {
      const codes = await this.detector.detect(el);
      return codes.find((c) => c.rawValue)?.rawValue ?? null;
    }
    if (!this.jsqr) return null;
    const scale = Math.min(1, MAX_DECODE_WIDTH / el.videoWidth);
    const w = Math.round(el.videoWidth * scale);
    const h = Math.round(el.videoHeight * scale);
    if (!this.canvas) {
      this.canvas = document.createElement('canvas');
      this.ctx = this.canvas.getContext('2d', { willReadFrequently: true } as CanvasRenderingContext2DSettings);
    }
    if (!this.ctx) return null;
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    this.ctx.drawImage(el, 0, 0, w, h);
    const img = this.ctx.getImageData(0, 0, w, h);
    const code = this.jsqr(img.data, w, h, { inversionAttempts: 'dontInvert' });
    return code?.data || null;
  }

  private onCameraChange = (e: React.ChangeEvent<HTMLSelectElement>): void => {
    // The user picked another camera: restart the stream with it.
    this.setState({ deviceId: e.target.value }, () => this.start());
  };

  private onRetry = (): void => {
    this.start();
  };

  public render(): React.ReactNode {
    const { active, paused, onError } = this.props;
    const { status, error, cameras, deviceId } = this.state;
    if (!active) return null;

    if (status === 'error') {
      // The parent shows the message itself when it handles onError.
      return onError ? null : (
        <div className="alert alert-warning d-flex gap-2 align-items-start" role="alert">
          <i className="bi bi-camera-video-off fs-4" aria-hidden="true" />
          <div className="flex-grow-1">{error}</div>
          <button type="button" className="btn btn-sm btn-outline-primary" onClick={this.onRetry}>Try again</button>
        </div>
      );
    }

    const corner: React.CSSProperties = { position: 'absolute', width: '18%', height: '18%', borderColor: '#fff', borderStyle: 'solid', borderWidth: 0 };
    const w = 4;
    return (
      <div className="card border-0 shadow-sm overflow-hidden mb-3" style={{ borderRadius: '1rem', maxWidth: 480 }}>
        <div style={{ position: 'relative', background: '#000', aspectRatio: '4 / 3' }}>
          <video
            ref={this.videoRef}
            playsInline
            muted
            autoPlay
            aria-label="Camera preview for scanning ticket QR codes"
            style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
          />
          {/* Framing overlay: darkened edges with a bright square in the middle. */}
          <div aria-hidden="true" style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', pointerEvents: 'none' }}>
            <div
              style={{
                position: 'relative',
                width: '62%',
                aspectRatio: '1 / 1',
                maxHeight: '80%',
                borderRadius: '0.75rem',
                boxShadow: '0 0 0 9999px rgba(0, 0, 0, 0.38)',
                opacity: paused ? 0.45 : 1,
                transition: 'opacity 0.2s',
              }}
            >
              <span style={{ ...corner, top: 0, left: 0, borderTopWidth: w, borderLeftWidth: w, borderTopLeftRadius: '0.75rem' }} />
              <span style={{ ...corner, top: 0, right: 0, borderTopWidth: w, borderRightWidth: w, borderTopRightRadius: '0.75rem' }} />
              <span style={{ ...corner, bottom: 0, left: 0, borderBottomWidth: w, borderLeftWidth: w, borderBottomLeftRadius: '0.75rem' }} />
              <span style={{ ...corner, bottom: 0, right: 0, borderBottomWidth: w, borderRightWidth: w, borderBottomRightRadius: '0.75rem' }} />
            </div>
          </div>
          <div
            style={{
              position: 'absolute', left: 0, right: 0, bottom: 0, padding: '0.4rem 0.75rem', color: '#fff',
              background: 'linear-gradient(transparent, rgba(0,0,0,0.65))', fontSize: '0.9rem',
            }}
          >
            {status === 'starting' ? (
              <><span className="spinner-border spinner-border-sm me-2" aria-hidden="true" />Starting camera…</>
            ) : paused ? (
              <><i className="bi bi-pause-circle me-1" aria-hidden="true" />Scanning paused</>
            ) : (
              <><i className="bi bi-upc-scan me-1" aria-hidden="true" />Hold the ticket QR inside the frame</>
            )}
          </div>
        </div>
        {cameras.length > 1 && (
          <div className="card-body py-2">
            <label htmlFor="qr-camera" className="visually-hidden">Camera</label>
            <select id="qr-camera" className="form-select form-select-sm" value={deviceId} onChange={this.onCameraChange}>
              {cameras.map((c, i) => (
                <option key={c.deviceId || i} value={c.deviceId}>{c.label || `Camera ${i + 1}`}</option>
              ))}
            </select>
          </div>
        )}
      </div>
    );
  }
}

export default QrScanner;
