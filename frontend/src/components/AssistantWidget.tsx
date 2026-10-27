import * as React from 'react';
import type { AxiosError } from 'axios';
import { assistantApi, AssistantLink, ChatMessage, PageContext } from '../api/assistant';
import { errorMessage } from '../api/client';
import { withI18n, WithI18nProps } from '../i18n';
import { withRouter, WithRouterProps } from '../utils/withRouter';

/*
 * Floating AI assistant (Claude, via /api/assistant/chat/). Hidden entirely when the server reports it is not
 * configured, and on panel/kiosk screens. Sits bottom-right and moves up while the install-app toast is shown.
 * The conversation is kept for this browser tab only (sessionStorage).
 */

type AssistantWidgetProps = WithI18nProps & WithRouterProps;

interface UiMessage extends ChatMessage {
  links?: AssistantLink[];
}

interface AssistantWidgetState {
  available: boolean;
  open: boolean;
  messages: UiMessage[];
  input: string;
  sending: boolean;
  error: string;
  limitReached: boolean;
  remaining: number | null;
  offset: number;
}

const STORE_KEY = 'aa_assistant_chat';
const HIDDEN_PREFIXES = ['/admin', '/kiosk'];
const SUGGESTIONS = ['assistant.suggest.taj', 'assistant.suggest.delhiForts', 'assistant.suggest.refund', 'assistant.suggest.children'];
const GAP = 16;

function loadStored(): UiMessage[] {
  try {
    const raw = sessionStorage.getItem(STORE_KEY);
    const parsed = raw ? (JSON.parse(raw) as UiMessage[]) : [];
    return Array.isArray(parsed) ? parsed.slice(-24) : [];
  } catch {
    return [];
  }
}

class AssistantWidgetBase extends React.Component<AssistantWidgetProps, AssistantWidgetState> {
  public state: AssistantWidgetState = {
    available: false, open: false, messages: loadStored(), input: '', sending: false, error: '',
    limitReached: false, remaining: null, offset: 0,
  };

  private mounted = false;
  private observer: MutationObserver | null = null;
  private launcherRef = React.createRef<HTMLButtonElement>();
  private inputRef = React.createRef<HTMLTextAreaElement>();
  private listRef = React.createRef<HTMLDivElement>();
  private titleId = 'assistant-title';

  public componentDidMount(): void {
    this.mounted = true;
    assistantApi
      .status()
      .then((s) => {
        if (!this.mounted) return;
        this.setState({
          available: s.available,
          remaining: s.remaining ?? null,
          limitReached: s.available && s.remaining === 0,
        });
      })
      .catch(() => undefined); // unavailable: stay hidden
    this.watchInstallPrompt();
  }

  public componentDidUpdate(_p: AssistantWidgetProps, prev: AssistantWidgetState): void {
    if (prev.messages !== this.state.messages) {
      try {
        sessionStorage.setItem(STORE_KEY, JSON.stringify(this.state.messages.slice(-24)));
      } catch {
        /* storage unavailable */
      }
    }
    if (prev.messages.length !== this.state.messages.length || prev.sending !== this.state.sending || (!prev.open && this.state.open)) {
      const list = this.listRef.current;
      if (list) list.scrollTop = list.scrollHeight;
    }
    if (!prev.open && this.state.open) this.inputRef.current?.focus();
  }

  public componentWillUnmount(): void {
    this.mounted = false;
    this.observer?.disconnect();
  }

  /** Keep clear of the install-app toast (also bottom-right): lift the launcher/panel above it while it shows. */
  private watchInstallPrompt(): void {
    const measure = (): void => {
      const toast = document.querySelector('[data-testid="install-prompt"]');
      const offset = toast ? Math.ceil(toast.getBoundingClientRect().height) + GAP : 0;
      if (this.mounted && offset !== this.state.offset) this.setState({ offset });
    };
    measure();
    if (typeof MutationObserver !== 'undefined') {
      this.observer = new MutationObserver(measure);
      this.observer.observe(document.body, { childList: true, subtree: true });
    }
  }

  private pageContext(): PageContext {
    const path = this.props.router.location.pathname;
    const match = /^\/museums\/([^/]+)/.exec(path);
    return match ? { path, museum: decodeURIComponent(match[1]) } : { path };
  }

  private toggle = (): void => {
    this.setState((s) => ({ open: !s.open }), () => {
      if (!this.state.open) this.launcherRef.current?.focus();
    });
  };

  private close = (): void => {
    this.setState({ open: false }, () => this.launcherRef.current?.focus());
  };

  private onKeyDown = (e: React.KeyboardEvent): void => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      this.close();
    }
  };

  private send = async (text?: string): Promise<void> => {
    const content = (text ?? this.state.input).trim();
    if (!content || this.state.sending || this.state.limitReached) return;
    const messages: UiMessage[] = [...this.state.messages, { role: 'user', content }];
    this.setState({ messages, input: '', error: '' });
    await this.request(messages);
  };

  private request = async (messages: UiMessage[]): Promise<void> => {
    this.setState({ sending: true, error: '' });
    try {
      const history: ChatMessage[] = messages.map(({ role, content }) => ({ role, content })).slice(-12);
      const reply = await assistantApi.chat(history, this.props.i18n.lang, this.pageContext());
      if (!this.mounted) return;
      this.setState({
        messages: [...messages, { role: 'assistant', content: reply.reply, links: reply.links }],
        remaining: reply.remaining,
        limitReached: reply.remaining === 0,
      });
    } catch (err) {
      if (!this.mounted) return;
      const status = (err as AxiosError)?.response?.status;
      if (status === 429) this.setState({ limitReached: true, remaining: 0 });
      else if (status === 503 && ((err as AxiosError<{ available?: boolean }>).response?.data?.available === false)) this.setState({ available: false });
      else this.setState({ error: errorMessage(err, this.props.i18n.t('assistant.error')) });
    } finally {
      if (this.mounted) this.setState({ sending: false });
    }
  };

  private retry = (): void => {
    const { messages } = this.state;
    if (messages.length && messages[messages.length - 1].role === 'user') this.request(messages);
  };

  private clear = (): void => {
    this.setState({ messages: [], error: '' });
    this.inputRef.current?.focus();
  };

  private openLink = (url: string): void => {
    if (/^https?:\/\//.test(url)) window.open(url, '_blank', 'noopener');
    else this.props.router.navigate(url);
    if (window.matchMedia?.('(max-width: 575.98px)').matches) this.setState({ open: false });
  };

  private onInputKey = (e: React.KeyboardEvent<HTMLTextAreaElement>): void => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      this.send();
    }
  };

  private renderMessage(m: UiMessage, i: number): React.ReactNode {
    const { t } = this.props.i18n;
    const mine = m.role === 'user';
    return (
      <div key={i} className={`d-flex mb-2 ${mine ? 'justify-content-end' : 'justify-content-start'}`}>
        <div style={{ maxWidth: '85%' }}>
          <span className="visually-hidden">{mine ? t('assistant.you') : t('assistant.bot')}: </span>
          <div
            className={`px-3 py-2 rounded-3 small ${mine ? 'bg-primary text-white' : 'bg-light border'}`}
            style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
          >
            {m.content}
          </div>
          {!!m.links?.length && (
            <div className="d-flex flex-wrap gap-1 mt-1" role="group" aria-label={t('assistant.linksLabel')}>
              {m.links.map((link) => (
                <button key={link.url} type="button" className="btn btn-outline-primary btn-sm" onClick={() => this.openLink(link.url)}>
                  {link.label}
                  <i className="bi bi-chevron-right ms-1" aria-hidden="true" />
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  private renderPanel(): React.ReactNode {
    const { t } = this.props.i18n;
    const { messages, input, sending, error, limitReached, remaining } = this.state;
    const lastIsUser = messages.length > 0 && messages[messages.length - 1].role === 'user';
    return (
      <div
        className="card shadow-lg border-0 mb-2"
        role="dialog"
        aria-modal="false"
        aria-labelledby={this.titleId}
        data-testid="assistant-panel"
        onKeyDown={this.onKeyDown}
        style={{ width: 'min(380px, calc(100vw - 32px))', height: 'min(560px, calc(100vh - 120px))', display: 'flex', flexDirection: 'column' }}
      >
        <div className="card-header bg-primary text-white d-flex align-items-start gap-2 py-2">
          <i className="bi bi-chat-dots fs-5 mt-1" aria-hidden="true" />
          <div className="me-auto">
            <h2 id={this.titleId} className="h6 mb-0 text-white" style={{ fontFamily: 'inherit' }}>{t('assistant.title')}</h2>
            <div className="small opacity-75">{t('assistant.subtitle')}</div>
          </div>
          {messages.length > 0 && (
            <button type="button" className="btn btn-sm btn-outline-light py-0" onClick={this.clear}>
              {t('assistant.clear')}
            </button>
          )}
          <button type="button" className="btn-close btn-close-white ms-1" aria-label={t('assistant.close')} onClick={this.close} />
        </div>

        <div ref={this.listRef} className="card-body overflow-auto flex-grow-1" aria-live="polite" aria-relevant="additions" data-testid="assistant-messages">
          <div className="d-flex mb-3">
            <div className="px-3 py-2 rounded-3 small bg-light border" style={{ maxWidth: '85%' }}>{t('assistant.welcome')}</div>
          </div>
          {messages.map((m, i) => this.renderMessage(m, i))}
          {messages.length === 0 && !limitReached && (
            <div>
              <div className="text-muted small mb-1">{t('assistant.suggestions')}</div>
              <div className="d-flex flex-wrap gap-1">
                {SUGGESTIONS.map((key) => (
                  <button key={key} type="button" className="btn btn-sm btn-outline-secondary text-start" onClick={() => this.send(t(key))}>
                    <i className="bi bi-lightbulb me-1" aria-hidden="true" />
                    {t(key)}
                  </button>
                ))}
              </div>
            </div>
          )}
          {sending && (
            <div className="d-flex align-items-center gap-2 text-muted small" role="status" data-testid="assistant-typing">
              <span className="spinner-grow spinner-grow-sm" aria-hidden="true" />
              {t('assistant.typing')}
            </div>
          )}
          {error && !sending && (
            <div className="alert alert-danger py-2 small d-flex align-items-center gap-2 mb-0" role="alert">
              <i className="bi bi-exclamation-triangle" aria-hidden="true" />
              <span className="me-auto">{error}</span>
              {lastIsUser && (
                <button type="button" className="btn btn-sm btn-outline-danger" onClick={this.retry}>
                  <i className="bi bi-arrow-repeat me-1" aria-hidden="true" />
                  {t('assistant.retry')}
                </button>
              )}
            </div>
          )}
          {limitReached && (
            <div className="alert alert-warning py-2 small mb-0" role="alert" data-testid="assistant-limit">
              <i className="bi bi-hourglass-split me-1" aria-hidden="true" />
              {t('assistant.limit')}
            </div>
          )}
        </div>

        <div className="card-footer bg-white">
          <form
            className="d-flex gap-2 align-items-end"
            onSubmit={(e) => {
              e.preventDefault();
              this.send();
            }}
          >
            <label htmlFor="assistant-input" className="visually-hidden">{t('assistant.inputLabel')}</label>
            <textarea
              id="assistant-input"
              ref={this.inputRef}
              className="form-control form-control-sm"
              rows={2}
              maxLength={1000}
              placeholder={t('assistant.placeholder')}
              value={input}
              disabled={limitReached}
              onChange={(e) => this.setState({ input: e.target.value })}
              onKeyDown={this.onInputKey}
              style={{ resize: 'none' }}
            />
            <button type="submit" className="btn btn-accent btn-sm" disabled={!input.trim() || sending || limitReached} aria-label={t('assistant.send')}>
              <i className="bi bi-arrow-up-circle-fill fs-5" aria-hidden="true" />
            </button>
          </form>
          <div className="d-flex justify-content-between mt-1" style={{ fontSize: '0.72rem' }}>
            <span className="text-muted">{t('assistant.disclaimer')}</span>
            {remaining !== null && !limitReached && <span className="text-muted text-nowrap ms-2">{t('assistant.remaining', { n: remaining })}</span>}
          </div>
        </div>
      </div>
    );
  }

  public render(): React.ReactNode {
    const { available, open, offset } = this.state;
    const path = this.props.router.location.pathname;
    if (!available || HIDDEN_PREFIXES.some((p) => path === p || path.startsWith(`${p}/`))) return null;
    const { t } = this.props.i18n;
    return (
      <div
        className="position-fixed end-0 d-flex flex-column align-items-end"
        style={{ bottom: offset, right: 0, zIndex: 1070, padding: GAP, pointerEvents: 'none' }}
        data-testid="assistant-widget"
      >
        <div style={{ pointerEvents: 'auto' }}>{open && this.renderPanel()}</div>
        <button
          ref={this.launcherRef}
          type="button"
          className="btn btn-primary rounded-circle shadow d-flex align-items-center justify-content-center"
          style={{ width: 56, height: 56, pointerEvents: 'auto' }}
          aria-label={open ? t('assistant.close') : t('assistant.open')}
          aria-expanded={open}
          aria-haspopup="dialog"
          title={t('assistant.open')}
          onClick={this.toggle}
          data-testid="assistant-launcher"
        >
          <i className={`bi ${open ? 'bi-x-lg' : 'bi-chat-dots'} fs-4`} aria-hidden="true" />
        </button>
      </div>
    );
  }
}

const AssistantWidget = withRouter(withI18n(AssistantWidgetBase));
export default AssistantWidget;
