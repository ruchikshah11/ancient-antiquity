import * as React from 'react';
import { EN, HI, loadLanguage, READY_LANGS } from '../loc';
import type { Dict } from '../loc';

/*
 * Visitor-facing UI in English, Hindi and more Indian languages. Admin screens and legal texts stay in English.
 * Strings live in the SPFx-style src/loc/<area>/ folders (see src/loc/index.ts); keys are flat and dotted.
 * A missing string falls back to English, and a missing key shows the key itself.
 * Placeholders: t('common.pagination.goTo', { page: 3 }) replaces {page}. Check coverage with `npm run i18n:check`.
 */

export type Lang = 'en' | 'hi' | 'gu' | 'mr' | 'ta' | 'te' | 'bn' | 'kn';
export type { Dict };

const DICTS: Partial<Record<Lang, Dict>> = { en: EN, hi: HI };

/** English source strings (used by tooling). */
export const SOURCE: Dict = EN;

const ALL_LANGS: { value: Lang; label: string; english: string; short: string; locale: string }[] = [
  { value: 'en', label: 'English', english: 'English', short: 'EN', locale: 'en-IN' },
  { value: 'hi', label: 'हिन्दी', english: 'Hindi', short: 'हि', locale: 'hi-IN' },
  { value: 'gu', label: 'ગુજરાતી', english: 'Gujarati', short: 'ગુ', locale: 'gu-IN' },
  { value: 'mr', label: 'मराठी', english: 'Marathi', short: 'म', locale: 'mr-IN' },
  { value: 'ta', label: 'தமிழ்', english: 'Tamil', short: 'த', locale: 'ta-IN' },
  { value: 'te', label: 'తెలుగు', english: 'Telugu', short: 'తె', locale: 'te-IN' },
  { value: 'bn', label: 'বাংলা', english: 'Bengali', short: 'বা', locale: 'bn-IN' },
  { value: 'kn', label: 'ಕನ್ನಡ', english: 'Kannada', short: 'ಕ', locale: 'kn-IN' },
];

/** Languages visitors can choose: English, Hindi and every language complete in all src/loc areas. */
export const LANGS = ALL_LANGS.filter((l) => l.value in DICTS || READY_LANGS.includes(l.value));

const STORAGE_KEY = 'aa_lang';
const isLang = (v: string | null | undefined): v is Lang => LANGS.some((l) => l.value === v);

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (isLang(saved)) return saved;
  } catch {
    /* storage unavailable */
  }
  const browser = navigator.language?.toLowerCase().slice(0, 2);
  return isLang(browser) ? browser : 'en';
}

let currentLang: Lang = initialLang();

/** Locale for dates/numbers in the current language (used by utils/format.ts). */
export const currentLocale = (): string => ALL_LANGS.find((l) => l.value === currentLang)?.locale ?? 'en-IN';

/** Load a language once; resolves immediately for English/Hindi or when already loaded. */
function loadLang(lang: Lang): Promise<void> {
  if (DICTS[lang] || !READY_LANGS.includes(lang)) return Promise.resolve();
  return loadLanguage(lang).then((dict) => {
    DICTS[lang] = dict;
  });
}

export function translate(lang: Lang, key: string, vars?: Record<string, string | number>): string {
  let text = DICTS[lang]?.[key] ?? DICTS.en?.[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) text = text.split(`{${k}}`).join(String(v));
  return text;
}

export interface I18nValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
}

export const I18nContext = React.createContext<I18nValue>({
  lang: currentLang,
  setLang: () => undefined,
  t: (key, vars) => translate(currentLang, key, vars),
});

interface I18nProviderState {
  lang: Lang;
  /** Bumped when a language file finishes loading, so translations refresh. */
  loaded: number;
}

export class I18nProvider extends React.Component<{ children: React.ReactNode }, I18nProviderState> {
  public state: I18nProviderState = { lang: currentLang, loaded: 0 };

  private value: I18nValue | null = null;
  private valueKey = '';

  public componentDidMount(): void {
    document.documentElement.lang = this.state.lang;
    // A saved non-English choice: show English until its file arrives (a fraction of a second).
    loadLang(this.state.lang).then(() => this.setState((s) => ({ loaded: s.loaded + 1 }))).catch(() => undefined);
  }

  private setLang = (lang: Lang): void => {
    loadLang(lang)
      .catch(() => undefined) // offline: falls back to English strings
      .then(() => {
        currentLang = lang;
        try {
          localStorage.setItem(STORAGE_KEY, lang);
        } catch {
          /* storage unavailable */
        }
        document.documentElement.lang = lang;
        this.setState((s) => ({ lang, loaded: s.loaded + 1 }));
      });
  };

  private getValue(): I18nValue {
    const { lang, loaded } = this.state;
    const key = `${lang}:${loaded}`;
    if (!this.value || this.valueKey !== key) {
      this.valueKey = key;
      this.value = { lang, setLang: this.setLang, t: (k, vars) => translate(lang, k, vars) };
    }
    return this.value;
  }

  public render(): React.ReactNode {
    return <I18nContext.Provider value={this.getValue()}>{this.props.children}</I18nContext.Provider>;
  }
}

export interface WithI18nProps {
  i18n: I18nValue;
}

/** Injects `i18n` ({ lang, setLang, t }) into a class component. */
export function withI18n<P extends WithI18nProps>(Component: React.ComponentType<P>) {
  class WithI18n extends React.Component<Omit<P, keyof WithI18nProps>> {
    public static displayName = `withI18n(${Component.displayName ?? Component.name})`;

    public render(): React.ReactNode {
      return <I18nContext.Consumer>{(i18n) => <Component {...(this.props as P)} i18n={i18n} />}</I18nContext.Consumer>;
    }
  }
  return WithI18n;
}
