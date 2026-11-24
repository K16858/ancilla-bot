import type {
  CompanionChatResponse,
  ConnState,
  Me,
  NotificationItem,
  SessionEndResponse,
  TimerItem,
  TimersPayload,
} from "./types";

const TOKEN_KEY = "ancilla.companion.token";
const SESSION_KEY = "ancilla.companion.sessionId";

export const getToken = (): string => localStorage.getItem(TOKEN_KEY) ?? "";
export const setToken = (t: string): void => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = (): void => localStorage.removeItem(TOKEN_KEY);

export function getSessionId(): string {
  let sid = localStorage.getItem(SESSION_KEY) ?? "";
  if (!sid) {
    const rand = Math.random().toString(36).slice(2, 10);
    sid = `companion-${rand}`;
    localStorage.setItem(SESSION_KEY, sid);
  }
  return sid;
}

export class Unauthorized extends Error {}
export class Forbidden extends Error {}
export class BusyError extends Error {}
export class ServiceUnavailableError extends Error {}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  return {
    Authorization: `Bearer ${getToken()}`,
    ...extra,
  };
}

async function handleJsonResponse<T>(r: Response): Promise<T> {
  if (r.status === 401) throw new Unauthorized("認証が必要です");
  if (r.status === 403) throw new Forbidden("権限が不足しています (operate ロールが必要です)");
  if (r.status === 409) throw new BusyError("他のチャネルで会話中です。少し待ってください。");
  if (r.status === 503) {
    const body = (await r.json().catch(() => ({}))) as { error?: string };
    throw new ServiceUnavailableError(body.error ?? "サービスが設定されていません");
  }
  const body = (await r.json().catch(() => ({}))) as { error?: string };
  if (!r.ok) {
    throw new Error(body.error ?? `HTTP ${r.status}`);
  }
  return body as T;
}

export async function fetchMe(tokenOverride?: string, signal?: AbortSignal): Promise<Me> {
  const token = tokenOverride ?? getToken();
  const r = await fetch("/api/v1/me", {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  });
  return handleJsonResponse<Me>(r);
}

export async function fetchTimers(all = false, signal?: AbortSignal): Promise<TimersPayload> {
  const qs = all ? "?all=1" : "";
  const r = await fetch(`/api/v1/timers${qs}`, {
    headers: authHeaders(),
    signal,
  });
  return handleJsonResponse<TimersPayload>(r);
}

export async function createTimer(durationSec: number, label = ""): Promise<TimerItem> {
  const r = await fetch("/api/v1/timers", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ duration_sec: durationSec, label }),
  });
  return handleJsonResponse<TimerItem>(r);
}

export async function updateTimer(
  id: string,
  patch: { duration_sec?: number; add_sec?: number; label?: string },
): Promise<TimerItem> {
  const r = await fetch(`/api/v1/timers/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(patch),
  });
  return handleJsonResponse<TimerItem>(r);
}

export async function stopTimer(id: string): Promise<TimerItem> {
  const r = await fetch(`/api/v1/timers/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ action: "stop" }),
  });
  return handleJsonResponse<TimerItem>(r);
}

export async function cancelTimer(id: string): Promise<TimerItem> {
  const r = await fetch(`/api/v1/timers/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  return handleJsonResponse<TimerItem>(r);
}

export async function fetchNotifications(
  sinceId = 0,
  limit = 50,
  signal?: AbortSignal,
): Promise<NotificationItem[]> {
  const params = new URLSearchParams();
  if (sinceId > 0) params.set("since_id", String(sinceId));
  params.set("limit", String(limit));
  const r = await fetch(`/api/v1/notifications?${params.toString()}`, {
    headers: authHeaders(),
    signal,
  });
  return handleJsonResponse<NotificationItem[]>(r);
}

export async function sendCompanionChat(
  message: string,
  opts?: { sessionId?: string; resetPending?: boolean; signal?: AbortSignal },
): Promise<CompanionChatResponse> {
  const r = await fetch("/api/v1/companion/chat", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      message,
      session_id: opts?.sessionId ?? getSessionId(),
      reset_pending: Boolean(opts?.resetPending),
    }),
    signal: opts?.signal,
  });
  return handleJsonResponse<CompanionChatResponse>(r);
}

export async function endCompanionSession(sessionId?: string): Promise<SessionEndResponse> {
  const r = await fetch("/api/v1/companion/session/end", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ session_id: sessionId ?? getSessionId() }),
  });
  return handleJsonResponse<SessionEndResponse>(r);
}

export async function cancelChat(): Promise<{ ok: boolean }> {
  const r = await fetch("/api/v1/chat/cancel", {
    method: "POST",
    headers: authHeaders(),
  });
  return handleJsonResponse<{ ok: boolean }>(r);
}

export async function transcribeVoice(
  audio: Blob,
  mimeType: string,
  prompt = "",
  signal?: AbortSignal,
): Promise<string> {
  const params = new URLSearchParams();
  if (prompt.trim()) params.set("prompt", prompt.trim());
  const qs = params.toString() ? `?${params.toString()}` : "";
  const r = await fetch(`/api/v1/voice/stt${qs}`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": mimeType || audio.type || "audio/webm" }),
    body: audio,
    signal,
  });
  const data = await handleJsonResponse<{ text?: string }>(r);
  return (data.text ?? "").trim();
}

export async function synthesizeVoice(text: string, signal?: AbortSignal): Promise<ArrayBuffer> {
  const r = await fetch("/api/v1/voice/tts", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ text }),
    signal,
  });
  if (r.status === 401) throw new Unauthorized("認証が必要です");
  if (r.status === 403) throw new Forbidden("権限が不足しています");
  if (r.status === 503) throw new ServiceUnavailableError("TTS_BASE_URL が未設定です");
  if (!r.ok) {
    const body = (await r.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error ?? `HTTP ${r.status}`);
  }
  return r.arrayBuffer();
}

export type StreamHandlers = {
  onConnected: () => void;
  onConn: (c: ConnState) => void;
  onUnauthorized: () => void;
  onTimersChanged: (payload: TimersPayload) => void;
  onTimerFired: (timer: TimerItem) => void;
  onNotification: (item: NotificationItem) => void;
  onGenericEvent?: (eventName: string) => void;
};

/** SSE を fetch で購読し、切断時は指数バックオフ＋追い付き付きで自動再接続する。 */
export async function streamCompanion(
  handlers: StreamHandlers,
  signal: AbortSignal,
  initialNotifId = 0,
): Promise<void> {
  let lastEventId = "";
  let lastNotifId = initialNotifId;
  let delay = 1000;

  while (!signal.aborted) {
    handlers.onConn(lastEventId || lastNotifId > 0 ? "retrying" : "connecting");
    try {
      const headers: Record<string, string> = { Authorization: `Bearer ${getToken()}` };
      if (lastEventId) headers["Last-Event-ID"] = lastEventId;
      const qs = lastNotifId > 0 ? `?after_notification=${lastNotifId}` : "";
      const r = await fetch(`/api/v1/stream${qs}`, { headers, signal });
      if (r.status === 401) {
        handlers.onUnauthorized();
        return;
      }
      if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);

      handlers.onConn("open");
      handlers.onConnected();
      delay = 1000;

      const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += value.replace(/\r\n?/g, "\n");
        let idx: number;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const block = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          let name = "message";
          let id = "";
          const dataLines: string[] = [];
          for (const line of block.split("\n")) {
            if (!line || line.startsWith(":")) continue;
            if (line.startsWith("event:")) name = line.slice(6).trim();
            else if (line.startsWith("id:")) id = line.slice(3).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
          }
          if (!dataLines.length && name === "message") continue;
          const rawData = dataLines.join("\n");
          if (id) {
            if (name === "notification") {
              const nid = Number(id);
              if (Number.isFinite(nid) && nid > lastNotifId) lastNotifId = nid;
            } else {
              lastEventId = id;
            }
          }

          if (name === "timers_changed") {
            try {
              handlers.onTimersChanged(JSON.parse(rawData) as TimersPayload);
            } catch {
              // ignore malformed payload
            }
          } else if (name === "timer_fired") {
            try {
              handlers.onTimerFired(JSON.parse(rawData) as TimerItem);
            } catch {
              // ignore malformed payload
            }
          } else if (name === "notification") {
            try {
              const n = JSON.parse(rawData) as NotificationItem;
              if (typeof n.id === "number" && n.id > lastNotifId) lastNotifId = n.id;
              handlers.onNotification(n);
            } catch {
              // ignore malformed payload
            }
          } else {
            handlers.onGenericEvent?.(name);
          }
        }
      }
    } catch {
      if (signal.aborted) return;
    }
    handlers.onConn("retrying");
    await new Promise((res) => setTimeout(res, delay));
    delay = Math.min(delay * 2, 30000);
  }
}
