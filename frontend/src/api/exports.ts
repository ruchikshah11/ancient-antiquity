import { api } from './client';

/* Background export jobs: /api/admin/exports/ (start, list), /<id>/ (status, delete), /<id>/download/. */

export type ExportKind =
  | 'bookings_csv'
  | 'bookings_xlsx'
  | 'bookings_pdf'
  | 'users_csv'
  | 'users_xlsx'
  | 'users_pdf';

export type ExportStatus = 'pending' | 'running' | 'done' | 'failed' | 'expired';

export type ExportFilters = Record<string, string | undefined>;

export interface ExportJob {
  id: number;
  kind: ExportKind;
  kind_label: string;
  filters: Record<string, string>;
  status: ExportStatus;
  status_label: string;
  row_count: number;
  total_rows: number | null;
  file_name: string;
  file_size: number;
  note: string;
  error: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  download_url: string | null;
}

export interface ExportJobList {
  results: ExportJob[];
  keep_days: number;
  pdf_max_rows: number;
}

export const EXPORTS_PAGE = '/admin/exports';

export const isActive = (job: ExportJob): boolean => job.status === 'pending' || job.status === 'running';

/** Start an export; empty filter values are dropped. */
export async function startExport(kind: ExportKind, filters: ExportFilters = {}): Promise<ExportJob> {
  const clean: Record<string, string> = {};
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== '') clean[k] = v;
  });
  const { data } = await api.post<ExportJob>('/admin/exports/', { kind, filters: clean });
  return data;
}

export async function listExports(): Promise<ExportJobList> {
  const { data } = await api.get<ExportJobList>('/admin/exports/');
  return data;
}

export async function deleteExport(id: number): Promise<void> {
  await api.delete(`/admin/exports/${id}/`);
}

/** Download a finished export with the auth header (the file is never at a public URL), then save it. */
export async function downloadExport(job: ExportJob): Promise<void> {
  const res = await api.get<Blob>(`/admin/exports/${job.id}/download/`, { responseType: 'blob' });
  const url = URL.createObjectURL(res.data);
  const a = document.createElement('a');
  a.href = url;
  a.download = job.file_name || `export-${job.id}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}
