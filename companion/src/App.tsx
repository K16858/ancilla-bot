import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  cancelTimer,
  clearToken,
  fetchMe,
  fetchNotifications,
  fetchTimers,
  getToken,
  streamCompanion,
} from "./api";
import { playChime, stopAllPlayback } from "./audio/audioEngine";
import { ChatView } from "./components/ChatView";
import { LoginView } from "./components/LoginView";
import { StandbyClockView } from "./components/StandbyClockView";
import { UnlockView } from "./components/UnlockView";
import { classifyNotification, isDndActive, loadSettings, saveSettings } from "./notifications";
import { computeClockOffsetMs } from "./timers";
import type {
  CompanionState,
  ConnState,
  DndSettings,
  Me,
  NotificationItem,
  TimerItem,
} from "./types";
import { useCompanionChat } from "./useCompanionChat";

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [authChecking, setAuthChecking] = useState<boolean>(() => Boolean(getToken()));
  const [state, setState] = useState<CompanionState>("uninitialized");
  const [conn, setConn] = useState<ConnState>("connecting");
  const [now, setNow] = useState<Date>(() => new Date());
  const [clockOffsetMs, setClockOffsetMs] = useState<number>(0);
  const [timers, setTimers] = useState<TimerItem[]>([]);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState<number>(0);
  const [toasts, setToasts] = useState<NotificationItem[]>([]);
  const [settings, setSettings] = useState<DndSettings>(() => loadSettings());
  const [bannerError, setBannerError] = useState<string>("");

  const settingsRef = useRef(settings);
  settingsRef.current = settings;

  const dndActive = useMemo(() => isDndActive(settings, now), [settings, now]);

  const handleLogout = useCallback(() => {
    stopAllPlayback();
    clearToken();
    setMe(null);
    setState("uninitialized");
    setTimers([]);
    setNotifications([]);
    setUnreadCount(0);
    setToasts([]);
    setBannerError("");
  }, []);

  const chat = useCompanionChat({
    settings,
    onStateChange: setState,
    onUnauthorized: handleLogout,
  });

  // Verify saved token on mount
  useEffect(() => {
    const token = getToken();
    if (!token) {
      setAuthChecking(false);
      return;
    }
    const ctrl = new AbortController();
    fetchMe(token, ctrl.signal)
      .then((info) => setMe(info))
      .catch(() => {
        clearToken();
        setMe(null);
      })
      .finally(() => setAuthChecking(false));
    return () => ctrl.abort();
  }, []);

  // 1-second local clock & timer display tick
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  // Persist settings
  useEffect(() => {
    saveSettings(settings);
  }, [settings]);

  const syncTimers = useCallback(async (signal?: AbortSignal) => {
    try {
      const payload = await fetchTimers(false, signal);
      setTimers(payload.timers);
      setClockOffsetMs(computeClockOffsetMs(payload.server_now));
    } catch {
      // handled cleanly by SSE retry or unauthorized
    }
  }, []);

  // Load initial state + subscribe to SSE when authenticated & unlocked
  useEffect(() => {
    if (!me || state === "uninitialized") return;

    const ctrl = new AbortController();
    let cancelled = false;

    const start = async () => {
      await syncTimers(ctrl.signal);
      let initialNotifId = 0;
      try {
        const recent = await fetchNotifications(0, 30, ctrl.signal);
        if (!cancelled) {
          setNotifications(recent);
          initialNotifId = recent.reduce((max, item) => Math.max(max, item.id), 0);
        }
      } catch {
        // ignore
      }
      if (cancelled) return;

      await streamCompanion(
        {
          onConnected: () => {
            void syncTimers(ctrl.signal);
          },
          onConn: (c) => setConn(c),
          onUnauthorized: () => handleLogout(),
          onTimersChanged: (payload) => {
            setTimers(payload.timers);
            setClockOffsetMs(computeClockOffsetMs(payload.server_now));
          },
          onTimerFired: () => {
            void syncTimers(ctrl.signal);
          },
          onNotification: (item) => {
            setNotifications((prev) => {
              if (prev.some((x) => x.id === item.id)) return prev;
              return [item, ...prev].slice(0, 100);
            });
            const curSettings = settingsRef.current;
            const dnd = isDndActive(curSettings, new Date());
            const action = classifyNotification(item, dnd);
            if (action === "ignore") return;
            setUnreadCount((c) => c + 1);
            if (action === "toast" || action === "interrupt") {
              setToasts((prev) => [item, ...prev].slice(0, 3));
              window.setTimeout(() => {
                setToasts((prev) => prev.filter((x) => x.id !== item.id));
              }, 6000);
              if (!dnd && !curSettings.muteNotificationSound) {
                playChime("notify");
              }
            }
          },
        },
        ctrl.signal,
        initialNotifId,
      );
    };

    void start();
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [me, state === "uninitialized", syncTimers, handleLogout]);

  const handleToggleDnd = () => {
    setSettings((prev) => ({ ...prev, manualEnabled: !prev.manualEnabled }));
  };

  const handleCancelTimer = async (id: string) => {
    try {
      await cancelTimer(id);
      await syncTimers();
    } catch (err) {
      setBannerError(err instanceof Error ? err.message : "タイマー取消に失敗しました");
    }
  };

  if (authChecking) {
    return (
      <main className="companion-shell">
        <div className="companion-center">
          <p className="muted">接続を確認しています...</p>
        </div>
      </main>
    );
  }

  if (!me) {
    return (
      <LoginView
        onLoggedIn={(info) => {
          setMe(info);
          setState("uninitialized");
        }}
      />
    );
  }

  if (state === "uninitialized") {
    return (
      <UnlockView
        me={me}
        onUnlocked={() => setState("standby")}
        onLogout={handleLogout}
      />
    );
  }

  if (
    state === "listening" ||
    state === "thinking" ||
    state === "speaking" ||
    state === "idle_in_chat"
  ) {
    return (
      <ChatView
        state={state}
        emotion={chat.emotion}
        audioLevel={chat.audioLevel}
        turns={chat.turns}
        silenceLeftSec={chat.silenceLeftSec}
        silenceTimeoutSec={settings.silenceTimeoutSec}
        micAvailable={chat.micAvailable}
        statusNote={chat.statusNote}
        onFinishSpeakingNow={chat.finishListeningNow}
        onCancelThinking={chat.cancelThinking}
        onInterruptSpeaking={chat.interruptSpeaking}
        onListenAgain={chat.listenAgain}
        onSubmitText={chat.submitText}
        onTypingActiveChange={chat.setTypingActive}
        onEndConversation={() => chat.exitToStandby(true)}
      />
    );
  }

  return (
    <StandbyClockView
      me={me}
      now={now}
      conn={conn}
      clockOffsetMs={clockOffsetMs}
      timers={timers}
      dndActive={dndActive}
      settings={settings}
      unreadCount={unreadCount}
      toasts={toasts}
      bannerError={bannerError}
      onDismissToast={(id) => setToasts((prev) => prev.filter((x) => x.id !== id))}
      onToggleDnd={handleToggleDnd}
      onStartChat={() => {
        setBannerError("");
        void chat.startChat();
      }}
      onCancelTimer={handleCancelTimer}
      onOpenNotifications={() => {
        setUnreadCount(0);
        setBannerError(
          notifications.length > 0
            ? `直近通知 (${notifications.length}件): ${notifications[0].message}`
            : "通知はありません",
        );
      }}
      onOpenSettings={() => setBannerError("設定画面は次のステップで追加されます")}
      onLogout={handleLogout}
    />
  );
}
