import { api } from './client';

/* AI visitor assistant (Claude). The widget is hidden unless the server says it is available. */

export interface AssistantStatus {
  available: boolean;
  daily_limit?: number;
  remaining?: number;
}

export interface AssistantLink {
  label: string;
  /** Site path, e.g. /museums/taj-mahal-agra?date=2026-11-02 */
  url: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatReply {
  reply: string;
  links: AssistantLink[];
  remaining: number;
}

export interface PageContext {
  path: string;
  museum?: string;
}

export const assistantApi = {
  status: () => api.get<AssistantStatus>('/assistant/status/').then((r) => r.data),
  chat: (messages: ChatMessage[], lang: string, pageContext?: PageContext) =>
    api
      .post<ChatReply>('/assistant/chat/', { messages, lang, page_context: pageContext }, { timeout: 90_000 })
      .then((r) => r.data),
};
