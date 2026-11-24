import type { TimerItem } from "./types";

/** サーバー時刻とのズレ（ms）を計算する。以後クライアント時計へ加算して残時間を出す。 */
export function computeClockOffsetMs(serverNowIso: string, clientNowMs = Date.now()): number {
  const parsed = Date.parse(serverNowIso);
  if (!Number.isFinite(parsed)) return 0;
  return parsed - clientNowMs;
}

/** 補正済み現在時刻に基づくタイマー残秒数（0 以上）。 */
export function remainingSeconds(
  timer: TimerItem,
  offsetMs: number,
  clientNowMs = Date.now(),
): number {
  if (timer.status !== "running") return 0;
  const endsMs = Date.parse(timer.ends_at);
  if (!Number.isFinite(endsMs)) return Math.max(0, timer.remaining_sec);
  const correctedNowMs = clientNowMs + offsetMs;
  return Math.max(0, Math.ceil((endsMs - correctedNowMs) / 1000));
}

/** 秒数を MM:SS または HH:MM:SS 表記へ整形する。 */
export function formatCountdown(totalSec: number): string {
  const sec = Math.max(0, Math.floor(totalSec));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  if (h > 0) {
    return `${String(h).padStart(2, "0")}:${mm}:${ss}`;
  }
  return `${mm}:${ss}`;
}

/** running 状態のタイマーがクライアント側補正時計で満了時刻に達したか判定する。 */
export function hasLocalTimerExpired(
  timer: TimerItem,
  offsetMs: number,
  clientNowMs = Date.now(),
): boolean {
  if (timer.status !== "running") return false;
  const endsMs = Date.parse(timer.ends_at);
  if (!Number.isFinite(endsMs)) return false;
  return clientNowMs + offsetMs >= endsMs;
}

/** firing を先頭に、残りは ends_at 昇順へ並べる。 */
export function sortTimers(timers: TimerItem[]): TimerItem[] {
  return [...timers].sort((a, b) => {
    if (a.status === "firing" && b.status !== "firing") return -1;
    if (b.status === "firing" && a.status !== "firing") return 1;
    return Date.parse(a.ends_at) - Date.parse(b.ends_at);
  });
}
