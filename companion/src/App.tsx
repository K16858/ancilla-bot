import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  cancelTimer,
  clearToken,
  createTimer,
  fetchMe,
  fetchNotifications,
  fetchTimers,
  getToken,
  stopTimer,
  streamCompanion,
  synthesizeVoice,
  Unauthorized,
} from "./api";
import {
  playChime,
  playWav,
  speakFallback,
  startAlarmLoop,
  stopAllPlayback,
} from "./audio/audioEngine";
import { NoopWakeWordEngine } from "./audio/wakeWord";
import { AlertOverlay } from "./components/AlertOverlay";
import { ChatView } from "./components/ChatView";
import { LoginView } from "./components/LoginView";
import { NotificationsDrawer } from "./components/NotificationsDrawer";
import { SettingsModal } from "./components/SettingsModal";
import { StandbyClockView } from "./components/StandbyClockView";
import { UnlockView } from "./components/UnlockView";
import {
  classifyNotification,
  isDndActive,
  loadSettings,
  notificationSummarySpeech,
  saveSettings,
} from "./notifications";
import { computeClockOffsetMs, hasLocalTimerExpired } from "./timers";
import type {
  AlertContext,
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
  const [alertContext, setAlertContext] = useState<AlertContext | null>(null);
  const [alertAudioLevel, setAlertAudioLevel] = useState<number>(0);
  const [drawerOpen, setDrawerOpen] = useState<boolean>(false);
  const [settingsOpen, setSettingsOpen] = useState<boolean>(false);

  const wakeWordEngine = useMemo(() => new NoopWakeWordEngine(), []);

  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const stateRef = useRef(state);
  stateRef.current = state;
  const alertContextRef = useRef(alertContext);
  alertContextRef.current = alertContext;
  const clockOffsetRef = useRef(clockOffsetMs);
  clockOffsetRef.current = clockOffsetMs;

  const alarmStopRef = useRef<(() => void) | null>(null);
  const alertAbortRef = useRef<AbortController | null>(null);
  const autoReturnTimerRef = useRef<number | null>(null);
  const triggeredTimerIdsRef = useRef<Set<string>>(new Set());
  const dismissedTimerIdsRef = useRef<Set<string>>(new Set());

  const dndActive = useMemo(() => isDndActive(settings, now), [settings, now]);

  const clearAlertMedia = useCallback(() => {
    if (autoReturnTimerRef.current !== null) {
      window.clearTimeout(autoReturnTimerRef.current);
      autoReturnTimerRef.current = null;
    }
    alarmStopRef.current?.();
    alarmStopRef.current = null;
    alertAbortRef.current?.abort();
    alertAbortRef.current = null;
    stopAllPlayback();
    setAlertAudioLevel(0);
  }, []);

  useEffect(() => {
    return () => {
      clearAlertMedia();
      void wakeWordEngine.stop();
    };
  }, [clearAlertMedia, wakeWordEngine]);

  const handleLogout = useCallback(() => {
    clearAlertMedia();
    clearToken();
    setMe(null);
    setState("uninitialized");
    setTimers([]);
    setNotifications([]);
    setUnreadCount(0);
    setToasts([]);
    setAlertContext(null);
    setDrawerOpen(false);
    setSettingsOpen(false);
    setBannerError("");
  }, [clearAlertMedia]);

  const chat = useCompanionChat({
    settings,
    onStateChange: setState,
    onUnauthorized: handleLogout,
  });
  const chatRef = useRef(chat);
  chatRef.current = chat;

  const speakAlertSpeech = useCallback(
    async (text: string, signal: AbortSignal) => {
      try {
        const wav = await synthesizeVoice(text, signal);
        if (signal.aborted) return;
        await playWav(wav, setAlertAudioLevel, signal);
      } catch (err) {
        if (signal.aborted) return;
        if (err instanceof Unauthorized) {
          handleLogout();
          return;
        }
        await speakFallback(text, setAlertAudioLevel, signal);
      } finally {
        if (!signal.aborted) setAlertAudioLevel(0);
      }
    },
    [handleLogout],
  );

  const stopAlert = useCallback(async () => {
    const ctx = alertContextRef.current;
    clearAlertMedia();
    setAlertContext(null);
    setState("standby");

    if (ctx?.kind === "timer") {
      for (const t of ctx.timers) {
        dismissedTimerIdsRef.current.add(t.id);
        try {
          await stopTimer(t.id);
        } catch {
          // If client clock fired slightly ahead of Core's 1s watcher, retry once shortly
          if (t.status === "running") {
            window.setTimeout(() => {
              void stopTimer(t.id).catch(() => {});
            }, 1100);
          }
        }
      }
      try {
        const payload = await fetchTimers(false);
        setTimers(payload.timers);
        setClockOffsetMs(computeClockOffsetMs(payload.server_now));
      } catch {
        // SSE will sync
      }
    }
  }, [clearAlertMedia]);

  const triggerTimerAlert = useCallback(
    (firingList: TimerItem[]) => {
      if (firingList.length === 0) return;
      for (const t of firingList) {
        triggeredTimerIdsRef.current.add(t.id);
      }

      if (alertContextRef.current?.kind === "timer") {
        setAlertContext({ kind: "timer", timers: firingList });
        return;
      }

      if (
        stateRef.current === "listening" ||
        stateRef.current === "thinking" ||
        stateRef.current === "speaking" ||
        stateRef.current === "idle_in_chat"
      ) {
        chatRef.current.exitToStandby(true);
      }

      clearAlertMedia();
      setDrawerOpen(false);
      setSettingsOpen(false);
      setAlertContext({ kind: "timer", timers: firingList });
      setState("alerting");

      alarmStopRef.current = startAlarmLoop();
      const ctrl = new AbortController();
      alertAbortRef.current = ctrl;
      const labels = firingList
        .map((t) => (t.label ? `${t.label}のタイマー` : "タイマー"))
        .join("、");
      void speakAlertSpeech(`${labels}の時間です。`, ctrl.signal);
    },
    [clearAlertMedia, speakAlertSpeech],
  );

  const triggerNotificationInterrupt = useCallback(
    async (item: NotificationItem) => {
      if (alertContextRef.current?.kind === "timer") return;

      if (
        stateRef.current === "listening" ||
        stateRef.current === "thinking" ||
        stateRef.current === "speaking" ||
        stateRef.current === "idle_in_chat"
      ) {
        chatRef.current.exitToStandby(true);
      }

      clearAlertMedia();
      setDrawerOpen(false);
      setSettingsOpen(false);
      setAlertContext({ kind: "notification", notification: item });
      setState("alerting");

      if (!settingsRef.current.muteNotificationSound) {
        playChime("notify");
      }

      const ctrl = new AbortController();
      alertAbortRef.current = ctrl;
      await speakAlertSpeech(notificationSummarySpeech(item), ctrl.signal);
      if (ctrl.signal.aborted) return;

      autoReturnTimerRef.current = window.setTimeout(() => {
        if (alertContextRef.current?.kind === "notification") {
          void stopAlert();
        }
      }, 10000);
    },
    [clearAlertMedia, speakAlertSpeech, stopAlert],
  );

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

  // 1-second local clock & local timer expiration check
  useEffect(() => {
    const id = window.setInterval(() => {
      const curNow = new Date();
      setNow(curNow);
      if (!me || stateRef.current === "uninitialized") return;
      const offset = clockOffsetRef.current;
      const activeIds = new Set(timers.map((t) => t.id));
      for (const tid of Array.from(dismissedTimerIdsRef.current)) {
        if (!activeIds.has(tid)) dismissedTimerIdsRef.current.delete(tid);
      }
      const due = timers.filter(
        (t) =>
          !dismissedTimerIdsRef.current.has(t.id) &&
          (t.status === "firing" || hasLocalTimerExpired(t, offset, curNow.getTime())),
      );
      const hasNew = due.some((t) => !triggeredTimerIdsRef.current.has(t.id));
      if (due.length > 0 && (hasNew || alertContextRef.current?.kind !== "timer")) {
        triggerTimerAlert(due);
      }
    }, 1000);
    return () => clearInterval(id);
  }, [me, timers, triggerTimerAlert]);

  // Persist settings
  useEffect(() => {
    saveSettings(settings);
  }, [settings]);

  const applyTimersPayload = useCallback(
    (nextTimers: TimerItem[], serverNowIso: string) => {
      const offset = computeClockOffsetMs(serverNowIso);
      setTimers(nextTimers);
      setClockOffsetMs(offset);

      const ids = new Set(nextTimers.map((t) => t.id));
      for (const tid of Array.from(triggeredTimerIdsRef.current)) {
        if (!ids.has(tid)) triggeredTimerIdsRef.current.delete(tid);
      }
      for (const tid of Array.from(dismissedTimerIdsRef.current)) {
        if (!ids.has(tid)) dismissedTimerIdsRef.current.delete(tid);
      }

      const firingOrExpired = nextTimers.filter(
        (t) =>
          !dismissedTimerIdsRef.current.has(t.id) &&
          (t.status === "firing" || hasLocalTimerExpired(t, offset)),
      );
      if (firingOrExpired.length > 0) {
        triggerTimerAlert(firingOrExpired);
      } else if (alertContextRef.current?.kind === "timer") {
        // Timer stopped/cancelled from CLI or another client (AC-5)
        clearAlertMedia();
        setAlertContext(null);
        setState("standby");
      }
    },
    [clearAlertMedia, triggerTimerAlert],
  );

  const syncTimers = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const payload = await fetchTimers(false, signal);
        applyTimersPayload(payload.timers, payload.server_now);
      } catch {
        // handled cleanly by SSE retry or unauthorized
      }
    },
    [applyTimersPayload],
  );

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
            applyTimersPayload(payload.timers, payload.server_now);
          },
          onTimerFired: (timer) => {
            if (!dismissedTimerIdsRef.current.has(timer.id)) {
              triggerTimerAlert([timer]);
            }
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
            if (action === "interrupt") {
              void triggerNotificationInterrupt(item);
            } else if (action === "toast") {
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
  }, [
    me,
    state === "uninitialized",
    syncTimers,
    applyTimersPayload,
    triggerTimerAlert,
    triggerNotificationInterrupt,
    handleLogout,
  ]);

  const handleToggleDnd = () => {
    setSettings((prev) => ({ ...prev, manualEnabled: !prev.manualEnabled }));
  };

  const handleCreateTimer = async (durationSec: number, label: string) => {
    await createTimer(durationSec, label);
    await syncTimers();
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

  if (state === "alerting" && alertContext) {
    return (
      <AlertOverlay
        alertContext={alertContext}
        audioLevel={alertAudioLevel}
        onStopAlert={() => void stopAlert()}
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
    <>
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
          setDrawerOpen(true);
        }}
        onOpenSettings={() => setSettingsOpen(true)}
        onLogout={handleLogout}
      />
      <NotificationsDrawer
        open={drawerOpen}
        me={me}
        nowMs={now.getTime()}
        clockOffsetMs={clockOffsetMs}
        timers={timers}
        notifications={notifications}
        onClose={() => setDrawerOpen(false)}
        onCreateTimer={handleCreateTimer}
        onCancelTimer={handleCancelTimer}
      />
      <SettingsModal
        open={settingsOpen}
        me={me}
        settings={settings}
        dndActive={dndActive}
        wakeWordName={wakeWordEngine.name}
        onChange={setSettings}
        onClose={() => setSettingsOpen(false)}
        onLogout={handleLogout}
      />
    </>
  );
}
