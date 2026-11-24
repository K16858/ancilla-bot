import type { DndSettings, NotificationItem } from "./types";

const SETTINGS_KEY = "ancilla.companion.settings";

export const DEFAULT_SETTINGS: DndSettings = {
  manualEnabled: false,
  scheduleEnabled: true,
  startTime: "23:00",
  endTime: "07:00",
  silenceTimeoutSec: 10,
  sttPrompt: "アンシラ、タイマー、キャンセル、ありがとう",
  muteNotificationSound: false,
};

export function loadSettings(): DndSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return { ...DEFAULT_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<DndSettings>;
    return {
      ...DEFAULT_SETTINGS,
      ...parsed,
      silenceTimeoutSec: Math.min(60, Math.max(4, Number(parsed.silenceTimeoutSec ?? DEFAULT_SETTINGS.silenceTimeoutSec) || 10)),
    };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function saveSettings(settings: DndSettings): void {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

function parseMinutes(hhmm: string): number | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm.trim());
  if (!m) return null;
  const h = Number(m[1]);
  const min = Number(m[2]);
  if (h < 0 || h > 23 || min < 0 || min > 59) return null;
  return h * 60 + min;
}

/** 手動トグルまたは夜間スケジュールによりおやすみモード中か判定する。 */
export function isDndActive(settings: DndSettings, now = new Date()): boolean {
  if (settings.manualEnabled) return true;
  if (!settings.scheduleEnabled) return false;
  const start = parseMinutes(settings.startTime);
  const end = parseMinutes(settings.endTime);
  if (start === null || end === null || start === end) return false;
  const cur = now.getHours() * 60 + now.getMinutes();
  if (start < end) {
    return cur >= start && cur < end;
  }
  return cur >= start || cur < end;
}

export type NotificationAction = "ignore" | "badge_only" | "toast" | "interrupt";

/** 通知種別・重要度とおやすみモードに応じて振る舞いを振り分ける。 */
export function classifyNotification(n: NotificationItem, dndActive: boolean): NotificationAction {
  if (n.category === "timer") return "ignore";
  if ((n.category === "incident" && n.level === "critical") || n.category === "reminder") {
    return dndActive ? "badge_only" : "interrupt";
  }
  return dndActive ? "badge_only" : "toast";
}

/** 重要通知・リマインダの読み上げ用短文を作る。 */
export function notificationSummarySpeech(n: NotificationItem): string {
  const title = (n.title ?? "").trim();
  const msg = n.message.trim();
  if (n.category === "reminder") {
    return title ? `リマインダです。${title}。${msg}` : `リマインダです。${msg}`;
  }
  if (n.category === "incident") {
    return title ? `重要なお知らせです。${title}。${msg}` : `重要なお知らせです。${msg}`;
  }
  return title ? `${title}。${msg}` : msg;
}
