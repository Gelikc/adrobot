export type Offer = { id: string; offer_id: number; name: string; active: boolean; share: number; pinned: boolean; published_active: boolean; new: boolean; remote_state: string };
export type Stream = { id: string; remote_id: number; name: string; position: number; revision: number; editable: boolean; missing: boolean; dirty: boolean; busy_operation: string | null; synced_at: string; offers: Offer[] };
export type Campaign = { id: string; remote_id: number; name: string; config: { alias?: string; domain_id?: number; group_id?: number; traffic_source_id?: number }; synced_at: string; streams: Stream[] };
export type Operation = { id: string; kind: string; status: string; step: string; error: string | null; created_at: string; data: { campaign_id?: string; remote_id?: number } };
export type Config = { mode: 'demo' | 'live'; keitaro_url: string; requires_login: boolean };
export type Ref = { id: number; name: string };
export type References = { domains: Ref[]; groups: Ref[]; traffic_sources: Ref[] };

export class ApiError extends Error {
  constructor(message: string, public status: number, public code: string) { super(message); }
}
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const r = await fetch('/api/v1' + path, {
    credentials: 'same-origin', ...options,
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'Adrobot', ...options.headers },
  });
  const data = await r.json();
  if (!r.ok) {
    const detail = Array.isArray(data.error?.details) ? data.error.details.map((x: { message: string }) => x.message).join(' ') : '';
    throw new ApiError((data.error?.message || 'Ошибка запроса') + (detail ? ' ' + detail : ''), r.status, data.error?.code);
  }
  return data as T;
}
export const post = <T,>(path: string, body: unknown = {}, key?: string) => api<T>(path, { method: 'POST', body: JSON.stringify(body), headers: key ? { 'Idempotency-Key': key } : {} });
