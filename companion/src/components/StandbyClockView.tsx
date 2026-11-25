import { useState } from "react";
import { formatCountdown, remainingSeconds, sortTimers } from "../timers";
import type { ConnState, DndSettings, Me, NotificationItem, TimerItem } from "../types";
import { AvatarView } from "./AvatarView";

type StandbyClockViewProps = {
  me: Me;
  now: Date;
  conn: ConnState;
  clockOffsetMs: number;
  timers: TimerItem[];
  dndActive: boolean;
  settings: DndSettings;
  unreadCount: number;
  toasts: NotificationItem[];
  bannerError?: string;
  onDismissToast: (id: number) => void;
  onToggleDnd: () => void;
  onStartChat: () => void;
  onCancelTimer: (id: string) => void;
  onOpenNotifications: () => void;
  onOpenSettings: () => void;
  onLogout: () => void;
};

export function StandbyClockView({
  me,
  now,
  conn,
  clockOffsetMs,
  timers,
  dndActive,
  settings,
  unreadCount,
  toasts,
  bannerError,
  onDismissToast,
  onToggleDnd,
  onStartChat,
  onCancelTimer,
  onOpenNotifications,
  onOpenSettings,
  onLogout,
}: StandbyClockViewProps) {
  const [isFullscreen, setIsFullscreen] = useState(Boolean(document.fullscreenElement));

  const correctedNow = new Date(now.getTime() + clockOffsetMs);
  const hhmm = new Intl.DateTimeFormat("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(correctedNow);
  const ss = String(correctedNow.getSeconds()).padStart(2, "0");
  const dateLabel = new Intl.DateTimeFormat("ja-JP", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
  }).format(correctedNow);

  const runningTimers = sortTimers(timers.filter((t) => t.status === "running"));

  const toggleFullscreen = async () => {
    try {
      if (!document.fullscreenElement) {
        await document.documentElement.requestFullscreen();
        setIsFullscreen(true);
      } else {
        await document.exitFullscreen();
        setIsFullscreen(false);
      }
    } catch {
      // ignore on browsers like iOS Safari without standard Fullscreen API
    }
  };

  const connLabel = conn === "open" ? "オンライン" : conn === "retrying" ? "再接続中…" : "接続中…";

  return (
    <main className="companion-shell standby-shell">
      <header className="top-bar">
        <div className="top-left">
          <span className="wordmark">Ancilla</span>
          <span className={`conn-status conn-${conn}`} role="status">
            <span className="dot" aria-hidden="true" />
            {connLabel}
          </span>
        </div>

        <nav className="top-actions" aria-label="端末操作">
          <button
            type="button"
            className={`nav-btn ${dndActive ? "is-active" : ""}`}
            onClick={onToggleDnd}
            title="おやすみモード切替"
          >
            {settings.manualEnabled ? "おやすみ(手動)" : dndActive ? "おやすみ(夜間)" : "おやすみ"}
          </button>
          <button
            type="button"
            className="nav-btn"
            onClick={onOpenNotifications}
          >
            通知
            {unreadCount > 0 && <span className="badge">{unreadCount}</span>}
          </button>
          <button type="button" className="nav-btn" onClick={onOpenSettings}>
            設定
          </button>
          <span className="nav-sep" aria-hidden="true" />
          <button type="button" className="nav-btn subtle" onClick={toggleFullscreen}>
            {isFullscreen ? "解除" : "全画面"}
          </button>
          <button type="button" className="nav-btn subtle" onClick={onLogout}>
            ログアウト
          </button>
        </nav>
      </header>

      {toasts.length > 0 && (
        <div className="toast-stack" aria-live="polite">
          {toasts.map((item) => (
            <div key={item.id} className="toast-card">
              <div className="toast-body">
                <strong className={`toast-title level-${item.level}`}>{item.title || item.category}</strong>
                <span>{item.message}</span>
              </div>
              <button
                type="button"
                className="toast-close"
                onClick={() => onDismissToast(item.id)}
                aria-label="閉じる"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      <section className="clock-center" aria-label="待機時計">
        <div className="clock-date">{dateLabel}</div>
        <div className="clock-digits tabular">
          <span className="clock-hm">{hhmm}</span>
          <span className="clock-sec">:{ss}</span>
        </div>

        <div className="mini-avatar-strip">
          <AvatarView state="standby" audioLevel={0} />
        </div>

        {runningTimers.length > 0 && (
          <div className="timers-list" aria-label="動作中タイマー">
            {runningTimers.map((t) => {
              const rem = remainingSeconds(t, clockOffsetMs, now.getTime());
              return (
                <div key={t.id} className="timer-row">
                  <span className="timer-label">{t.label || "タイマー"}</span>
                  <div className="timer-row-right">
                    <span className="timer-time tabular">{formatCountdown(rem)}</span>
                    {me.role === "operate" && (
                      <button
                        type="button"
                        className="chip-cancel"
                        onClick={() => onCancelTimer(t.id)}
                        title="タイマーを取り消す"
                      >
                        取消
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <footer className="standby-footer">
        {bannerError && <p className="error-text">{bannerError}</p>}
        <button
          type="button"
          className="primary-btn large-btn"
          onClick={onStartChat}
          disabled={me.role !== "operate"}
        >
          タップして話す
        </button>
        {me.role !== "operate" && (
          <p className="muted">閲覧専用 (read) トークンのため音声対話は無効です</p>
        )}
      </footer>
    </main>
  );
}
