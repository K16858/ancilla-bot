import { useState } from "react";
import { unlockAudio } from "../audio/audioEngine";
import type { Me } from "../types";
import { AvatarView } from "./AvatarView";

type UnlockViewProps = {
  me: Me;
  onUnlocked: () => void;
  onLogout: () => void;
};

type NavigatorWithWakeLock = Navigator & {
  wakeLock?: { request(type: "screen"): Promise<unknown> };
};

export function UnlockView({ me, onUnlocked, onLogout }: UnlockViewProps) {
  const [busy, setBusy] = useState(false);

  const handleStart = async () => {
    setBusy(true);
    try {
      await unlockAudio();
      try {
        await (navigator as NavigatorWithWakeLock).wakeLock?.request("screen");
      } catch {
        // WakeLock が使えない環境でも進行する
      }
      onUnlocked();
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="companion-shell">
      <div className="companion-center unlock-screen">
        <AvatarView
          state="standby"
          audioLevel={0}
          statusText="タップして音声と通知を有効化してください"
        />
        <div className="unlock-meta">
          <span className="pill">接続: {me.name} ({me.role})</span>
        </div>
        <button
          type="button"
          className="primary-btn large-btn"
          onClick={handleStart}
          disabled={busy}
        >
          {busy ? "準備中..." : "タップして開始"}
        </button>
        <button type="button" className="ghost-btn" onClick={onLogout}>
          トークンを変更
        </button>
      </div>
    </main>
  );
}
