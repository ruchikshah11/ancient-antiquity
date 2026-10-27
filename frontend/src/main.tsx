import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import AssistantWidget from './components/AssistantWidget';
import InstallPrompt from './components/InstallPrompt';
import { AuthProvider } from './context/AuthContext';
import { I18nProvider } from './i18n';
import 'bootstrap-icons/font/bootstrap-icons.css';
import './styles/theme.scss';

// Offline app shell for gate/counter devices + installable app + push reminders
// (production builds only; the dev server reloads too often. ReminderSettings registers it on demand.)
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => undefined));
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <I18nProvider>
      <AuthProvider>
        <App />
        <InstallPrompt />
        <AssistantWidget />
      </AuthProvider>
      </I18nProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
