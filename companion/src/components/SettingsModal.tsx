import type { DndSettings, Me } from "../types";

type SettingsModalProps = {
  open: boolean;
  me: Me;
  settings: DndSettings;
  dndActive: boolean;
  wakeWordName: string;
  onChange: (next: DndSettings) => void;
  onClose: () => void;
  onLogout: () => void;
};

export function SettingsModal({
  open,
  me,
  settings,
  dndActive,
  wakeWordName,
  onChange,
  onClose,
  onLogout,
}: SettingsModalProps) {
  if (!open) return null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <section
        className="card-panel settings-modal"
        onClick={(e) => e.stopPropagation()}
        aria-label="コンパニオン設定"
      >
        <header className="drawer-header">
          <h2>コンパニオン設定</h2>
          <button type="button" className="nav-btn" onClick={onClose}>
            閉じる
          </button>
        </header>

        <div className="settings-grid">
          <div className="setting-row-block">
            <div className="setting-row">
              <label htmlFor="dnd-manual">おやすみモード（手動）</label>
              <input
                id="dnd-manual"
                type="checkbox"
                checked={settings.manualEnabled}
                onChange={(e) =>
                  onChange({ ...settings, manualEnabled: e.target.checked })
                }
              />
            </div>
            <p className="muted setting-note">
              現在: <strong>{dndActive ? "おやすみ抑制中" : "通常通知"}</strong>。
              タイマー満了はおやすみ中も鳴動し、HomeLab critical 等の他通知はサイレント蓄積されます。
            </p>
          </div>

          <div className="setting-row-block">
            <div className="setting-row">
              <label htmlFor="dnd-schedule">夜間スケジュール抑制</label>
              <input
                id="dnd-schedule"
                type="checkbox"
                checked={settings.scheduleEnabled}
                onChange={(e) =>
                  onChange({ ...settings, scheduleEnabled: e.target.checked })
                }
              />
            </div>
            <div className="time-range-row">
              <label>
                開始
                <input
                  type="time"
                  className="text-input"
                  value={settings.startTime}
                  disabled={!settings.scheduleEnabled}
                  onChange={(e) =>
                    onChange({ ...settings, startTime: e.target.value })
                  }
                />
              </label>
              <label>
                終了
                <input
                  type="time"
                  className="text-input"
                  value={settings.endTime}
                  disabled={!settings.scheduleEnabled}
                  onChange={(e) =>
                    onChange({ ...settings, endTime: e.target.value })
                  }
                />
              </label>
            </div>
          </div>

          <div className="setting-row-block">
            <label htmlFor="silence-sec">会話後の無言タイムアウト（秒）</label>
            <input
              id="silence-sec"
              type="number"
              min={4}
              max={60}
              className="text-input"
              value={settings.silenceTimeoutSec}
              onChange={(e) =>
                onChange({
                  ...settings,
                  silenceTimeoutSec: Math.min(
                    60,
                    Math.max(4, Number(e.target.value) || 10),
                  ),
                })
              }
            />
            <div className="setting-row setting-inline-toggle">
              <label htmlFor="mute-chime">控えめ通知音を消音</label>
              <input
                id="mute-chime"
                type="checkbox"
                checked={settings.muteNotificationSound}
                onChange={(e) =>
                  onChange({
                    ...settings,
                    muteNotificationSound: e.target.checked,
                  })
                }
              />
            </div>
          </div>

          <div className="setting-row-block">
            <label htmlFor="stt-prompt">音声認識 (STT) ヒント語</label>
            <input
              id="stt-prompt"
              type="text"
              className="text-input"
              value={settings.sttPrompt}
              onChange={(e) =>
                onChange({ ...settings, sttPrompt: e.target.value })
              }
            />
          </div>
        </div>

        <footer className="panel-footer-note settings-footer">
          <div className="muted settings-meta">
            <div>
              <strong>起動方式:</strong> タップ起動（engine: <code>{wakeWordName}</code>、Step 4 で差し替え予定）
            </div>
            <div>
              <strong>接続トークン:</strong> {me.name} ({me.role})
            </div>
          </div>
          <button
            type="button"
            className="ghost-btn danger-outline"
            onClick={onLogout}
          >
            ログアウト
          </button>
        </footer>
      </section>
    </div>
  );
}
