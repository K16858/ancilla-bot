import type { AlertContext } from "../types";
import { AvatarView } from "./AvatarView";

type AlertOverlayProps = {
  alertContext: AlertContext;
  audioLevel: number;
  onStopAlert: () => void;
};

export function AlertOverlay({
  alertContext,
  audioLevel,
  onStopAlert,
}: AlertOverlayProps) {
  const isTimer = alertContext.kind === "timer";

  return (
    <main
      className="companion-shell alert-shell"
      onClick={isTimer ? onStopAlert : undefined}
    >
      <div
        className="companion-center alert-card"
        onClick={(e) => e.stopPropagation()}
      >
        <AvatarView
          state="alerting"
          emotion="alert"
          audioLevel={audioLevel}
          statusText={isTimer ? "タイマー満了" : "重要なお知らせ"}
        />

        {isTimer ? (
          <div className="alert-details">
            {alertContext.timers.map((t) => (
              <div key={t.id} className="alert-timer-row">
                <h2>{t.label || "タイマー"} — 時間です！</h2>
                <p className="muted">
                  ID: {t.id} / 設定 {t.duration_sec} 秒
                </p>
              </div>
            ))}
          </div>
        ) : (
          <div className="alert-details">
            <span className="pill alert-pill">
              {alertContext.notification.category === "reminder"
                ? "リマインダ"
                : `HomeLab (${alertContext.notification.level})`}
            </span>
            {alertContext.notification.title && (
              <h2>{alertContext.notification.title}</h2>
            )}
            <p className="alert-msg">{alertContext.notification.message}</p>
            <p className="muted">
              読み上げ完了後、約 10 秒で時計画面へ戻ります
            </p>
          </div>
        )}

        <button
          type="button"
          className="primary-btn large-btn stop-alert-btn"
          onClick={onStopAlert}
        >
          {isTimer ? "アラームを止める" : "閉じる"}
        </button>
      </div>
    </main>
  );
}
