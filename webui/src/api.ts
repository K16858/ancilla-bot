const KEY = "ancilla.webui.token";

export const getToken = () => localStorage.getItem(KEY) ?? "";
export const setToken = (t: string) => localStorage.setItem(KEY, t);
export const clearToken = () => localStorage.removeItem(KEY);

export class Unauthorized extends Error {}

export async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(`/api/v1${path}`, { headers: { Authorization: `Bearer ${getToken()}` }, signal });
  if (r.status === 401) throw new Unauthorized();
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error ?? `HTTP ${r.status}`);
  return body as T;
}

export async function post<T>(path: string): Promise<T> {
  const r = await fetch(`/api/v1${path}`, { method: "POST", headers: { Authorization: `Bearer ${getToken()}` } });
  if (r.status === 401) throw new Unauthorized();
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error ?? `HTTP ${r.status}`);
  return body as T;
}

export type Conn = "connecting" | "open" | "retrying";

/** SSE を fetch で読む（EventSource は Authorization を付けられない）。signal で停止。 */
export async function stream(
  onEvent: (name: string) => void,
  onConn: (c: Conn) => void,
  onUnauthorized: () => void,
  signal: AbortSignal,
): Promise<void> {
  let lastId = "";
  let delay = 1000;
  while (!signal.aborted) {
    onConn(lastId ? "retrying" : "connecting");
    try {
      const headers: Record<string, string> = { Authorization: `Bearer ${getToken()}` };
      if (lastId) headers["Last-Event-ID"] = lastId;
      const r = await fetch("/api/v1/stream", { headers, signal });
      if (r.status === 401) return onUnauthorized();
      if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);
      onConn("open");
      onEvent("connected"); // 切断中に変わった分を取り直す
      delay = 1000;
      const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += value.replace(/\r\n?/g, "\n");
        let i: number;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const block = buf.slice(0, i);
          buf = buf.slice(i + 2);
          let name = "message";
          let id = "";
          for (const line of block.split("\n")) {
            if (line.startsWith("event:")) name = line.slice(6).trim();
            else if (line.startsWith("id:")) id = line.slice(3).trim();
          }
          if (id) lastId = id;
          if (name === "homelab_event" || name === "incidents_changed" || name === "approvals_changed") onEvent(name);
        }
      }
    } catch {
      if (signal.aborted) return;
    }
    onConn("retrying");
    await new Promise((res) => setTimeout(res, delay));
    delay = Math.min(delay * 2, 30000);
  }
}

// ---- 型（API の返す形。必要な所だけ） ----
export type Evidence = { source: string; freshness: string; observed_at: string | null; values: unknown };
export type Status = { id: string; type: string; state: string; flags: string[]; evidence: Evidence[]; mismatches: string[] };
export type Host = {
  id: string; name: string; os: string; role: string; criticality: string; address: string; node: boolean;
  status: Status; evaluated_at: string; services?: string[];
};
export type Service = {
  id: string; name: string; host: string; kind: string; unit: string; health_url: string; criticality: string;
  depends_on: string[]; status: Status; evaluated_at: string; impact?: { dependencies: string[]; dependents: string[] };
};
export type Summary = {
  evaluated_at: string; hosts: Record<string, number>; services: Record<string, number>;
  open_incidents: Record<string, number>;
};
export type NodeInfo = {
  host_id: string; connected: boolean; last_seen: string | null; os: string | null; version: string | null;
  hostname: string | null;
};
export type Incident = {
  id: string; subject: string; kind: string; severity: string; status: string; detected_at: string;
  acknowledged_at: string | null; resolved_at: string | null; resolved_by: string | null; diagnosis_status: string | null;
};
export type IncidentDetail = Incident & {
  affected_services: string[]; diagnosis: string | null;
  events: { id: number; role: string; subject: string; kind: string; from: string; to: string; detected_at: string; evidence: Evidence[] }[];
};
export type Approval = {
  run_id: string; tool: string; args: Record<string, unknown>; description: string;
  created_at: string; expires_at: string; source: string;
};
export type Me = { name: string; role: "read" | "operate" };
