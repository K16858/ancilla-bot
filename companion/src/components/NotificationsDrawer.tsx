import { useState, type FormEvent } from "react";
import { formatCountdown, remainingSeconds, sortTimers } from "../timers";
import type { Me, NotificationItem, TimerItem } from "../types";

type NotificationsDrawerProps = {
  open: boolean;
  me: Me;
  nowMs: number;
  clockOffsetMs: number;
  timers: TimerItem[];
  notifications: NotificationItem[];
  onClose: () => void;
  onCreateTimer: (durationSec: number, label: string) => Promise<void>;
  onCancelTimer: (id: string) => Promise<void>;
};

export function NotificationsDrawer({
  open,
  me,
  nowMs,
  clockOffsetMs,
  timers,
  notifications,
  onClose,
  onCreateTimer,
  onCancelTimer,
}: NotificationsDrawerProps) {
  const [amount, setAmount] = useState("3");
  const [unit, setUnit] = useState<"min" | "sec">("min");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  if (!open) return null;

  const running = sortTimers(timers.filter((t) => t.status === "running"));

  const runCreate = async (sec: number, timerLabel: string) => {
    setBusy(true);
    setErr("");
    try {
      await onCreateTimer(sec, timerLabel);
      setLabel("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "作成に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const num = Number(amount);
    if (!Number.isFinite(num) || num <= 0) {
      setErr("正の数を入力してください");
      return;
    }
    const sec = unit === "min" ? Math.round(num * 60) : Math.round(num);
    void runCreate(sec, label.trim());
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <aside
        className="drawer-panel"
        onClick={(e) => e.stopPropagation()}
        aria-label="通知とタイマー管理"
      >
        <header className="drawer-header">
          <h2>通知・タイマー</h2>
          <button type="button" className="icon-btn" onClick={onClose}>
            閉じる
          </button>
        </header>

        <section className="drawer-section">
          <h3>タイマー</h3>
          {me.role === "operate" && (
            <>
              <div className="preset-row">
                <button
                  type="button"
                  className="icon-btn"
                  disabled={busy}
                  onClick={() => void runCreate(60, "")}
                >
                  + 1分
                </button>
                <button
                  type="button"
                  className="icon-btn"
                  disabled={busy}
                  onClick={() => void runCreate(180, "")}
                >
                  + 3分
                </button>
                <button
                  type="button"
                  className="icon-btn"
                  disabled={busy}
                  onClick={() => void runCreate(300, "")}
                >
                  + 5分
                </button>
              </div>
              <form className="timer-create-form" onSubmit={handleSubmit}>
                <input
                  type="number"
                  min={1}
                  className="text-input num-input"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  disabled={busy}
                />
                <select
                  className="text-input unit-select"
                  value={unit}
                  onChange={(e) => setUnit(e.target.value as "min" | "sec")}
                  disabled={busy}
                >
                  <option value="min">分</option>
                  <option value="sec">秒</option>
                </select>
                <input
                  type="text"
                  className="text-input"
                  placeholder="ラベル（任意）"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  disabled={busy}
                />
                <button type="submit" className="primary-btn" disabled={busy}>
                  開始
                </button>
              </form>
              {err && <p className="error-text">{err}</p>}
            </>
          )}

          {running.length === 0 ? (
            <p className="muted">動作中のタイマーはありません</p>
          ) : (
            <ul className="drawer-list">
              {running.map((t) => (
                <li key={t.id} className="drawer-item">
                  <div>
                    <strong>{t.label || "タイマー"}</strong>
                    <div className="muted">
                      {t.id} ・ 残り{" "}
                      <span className="tabular">
                        {formatCountdown(remainingSeconds(t, clockOffsetMs, nowMs))}
                      </span>
                    </div>
                  </div>
                  {me.role === "operate" && (
                    <button
                      type="button"
                      className="chip-cancel"
                      onClick={() => void onCancelTimer(t.id)}
                    >
                      取消
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="drawer-section">
          <h3>最近の通知 ({notifications.length})</h3>
          {notifications.length === 0 ? (
            <p className="muted">通知履歴はまだありません</p>
          ) : (
            <ul className="drawer-list">
              {notifications.map((n) => (
                <li key={n.id} className={`drawer-item level-${n.level}`}>
                  <div className="notif-meta">
                    <span className="pill">
                      {n.category} / {n.level}
                    </span>
                    <span className="muted">{n.created_at.slice(11, 19)}</span>
                  </div>
                  {n.title && <strong>{n.title}</strong>}
                  <p className="notif-msg">{n.message}</p>
                  {n.detail && <p className="muted notif-detail">{n.detail}</p>}
                </li>
              ))}
            </ul>
          )}
        </section>
      </aside>
    </div>
  );
}
