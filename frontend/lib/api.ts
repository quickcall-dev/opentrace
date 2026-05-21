import type { Stats, Session, Message } from "./types";

const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "admin_dev";

function qs(params: Record<string, string | number | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v != null && v !== "") q.set(k, String(v));
  }
  const s = q.toString();
  return s ? "?" + s : "";
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, {
    headers: { "X-API-Key": API_KEY },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export const tracesApi = {
  stats: () => get<Stats>("/api/stats"),

  sessions: (params?: { source?: string; date?: string; user_email?: string; limit?: number; offset?: number }) =>
    get<Session[]>(`/api/sessions${qs({ source: params?.source, date: params?.date, user_email: params?.user_email, limit: params?.limit, offset: params?.offset })}`),

  session: (sessionId: string) =>
    get<Session[]>(`/api/sessions?id=${encodeURIComponent(sessionId)}`).then((arr) => arr[0] ?? null),

  messages: (sessionId: string, params?: { limit?: number; offset?: number }) =>
    get<Message[]>(`/api/messages${qs({ session_id: sessionId, limit: params?.limit, offset: params?.offset })}`),
};
