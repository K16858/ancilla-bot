import { useCallback, useEffect, useRef, useState } from "react";
import {
  BusyError,
  cancelChat,
  endCompanionSession,
  sendCompanionChat,
  ServiceUnavailableError,
  synthesizeVoice,
  transcribeVoice,
  Unauthorized,
} from "./api";
import {
  playChime,
  playWav,
  speakFallback,
  stopAllPlayback,
} from "./audio/audioEngine";
import {
  acquireMicStream,
  isMicSupported,
  startUtteranceCapture,
} from "./audio/vadRecorder";
import type { CompanionState, DndSettings, Emotion, SubtitleTurn } from "./types";

type UseCompanionChatArgs = {
  settings: DndSettings;
  onStateChange: (next: CompanionState) => void;
  onUnauthorized: () => void;
};

function makeTurn(role: "user" | "assistant", text: string, emotion?: Emotion | null): SubtitleTurn {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    role,
    text,
    emotion,
    at: Date.now(),
  };
}

export function useCompanionChat({
  settings,
  onStateChange,
  onUnauthorized,
}: UseCompanionChatArgs) {
  const [turns, setTurns] = useState<SubtitleTurn[]>([]);
  const [emotion, setEmotion] = useState<Emotion | null>(null);
  const [audioLevel, setAudioLevel] = useState<number>(0);
  const [silenceLeftSec, setSilenceLeftSec] = useState<number | null>(null);
  const [micAvailable, setMicAvailable] = useState<boolean>(() => isMicSupported());
  const [statusNote, setStatusNote] = useState<string>("");

  const sessionEpochRef = useRef<number>(0);
  const turnAbortRef = useRef<AbortController | null>(null);
  const finishRecRef = useRef<(() => void) | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const silenceIntervalRef = useRef<number | null>(null);
  const typingActiveRef = useRef<boolean>(false);
  const resetNextTurnRef = useRef<boolean>(false);
  const settingsRef = useRef<DndSettings>(settings);
  settingsRef.current = settings;

  const clearSilenceTimer = useCallback(() => {
    if (silenceIntervalRef.current !== null) {
      window.clearInterval(silenceIntervalRef.current);
      silenceIntervalRef.current = null;
    }
    setSilenceLeftSec(null);
  }, []);

  const stopMicStream = useCallback(() => {
    const stream = micStreamRef.current;
    micStreamRef.current = null;
    if (stream) {
      for (const track of stream.getTracks()) {
        track.stop();
      }
    }
  }, []);

  const abortCurrentTurn = useCallback((): number => {
    const epoch = ++sessionEpochRef.current;
    clearSilenceTimer();
    finishRecRef.current = null;
    turnAbortRef.current?.abort();
    turnAbortRef.current = null;
    stopAllPlayback();
    setAudioLevel(0);
    return epoch;
  }, [clearSilenceTimer]);

  const exitToStandby = useCallback(
    (notifyCore: boolean) => {
      abortCurrentTurn();
      stopMicStream();
      typingActiveRef.current = false;
      setTurns([]);
      setEmotion(null);
      setStatusNote("");
      onStateChange("standby");
      if (notifyCore) {
        resetNextTurnRef.current = true;
        void endCompanionSession().catch(() => {});
      }
    },
    [abortCurrentTurn, onStateChange, stopMicStream],
  );

  // Clean up resources on unmount
  useEffect(() => {
    return () => {
      sessionEpochRef.current += 1;
      clearSilenceTimer();
      turnAbortRef.current?.abort();
      stopAllPlayback();
      stopMicStream();
    };
  }, [clearSilenceTimer, stopMicStream]);

  const startIdleCountdown = useCallback(
    (epoch: number) => {
      clearSilenceTimer();
      const total = Math.max(4, settingsRef.current.silenceTimeoutSec);
      let left = total;
      setSilenceLeftSec(left);
      silenceIntervalRef.current = window.setInterval(() => {
        if (sessionEpochRef.current !== epoch) {
          clearSilenceTimer();
          return;
        }
        if (typingActiveRef.current) return;
        left -= 1;
        setSilenceLeftSec(Math.max(0, left));
        if (left <= 0) {
          exitToStandby(true);
        }
      }, 1000);
    },
    [clearSilenceTimer, exitToStandby],
  );

  const ensureMicStream = useCallback(async (): Promise<MediaStream | null> => {
    if (micStreamRef.current) {
      const live = micStreamRef.current.getTracks().some((t) => t.readyState === "live");
      if (live) return micStreamRef.current;
      micStreamRef.current = null;
    }
    if (!isMicSupported()) {
      setMicAvailable(false);
      return null;
    }
    try {
      const stream = await acquireMicStream();
      micStreamRef.current = stream;
      setMicAvailable(true);
      return stream;
    } catch {
      setMicAvailable(false);
      return null;
    }
  }, []);

  const runListenTurnRef = useRef<(epoch: number, isFollowUp: boolean) => Promise<void>>(
    async () => {},
  );

  const submitUtterance = useCallback(
    async (userText: string, epoch: number) => {
      if (sessionEpochRef.current !== epoch) return;
      const clean = userText.trim();
      if (!clean) {
        await runListenTurnRef.current(epoch, true);
        return;
      }

      clearSilenceTimer();
      setStatusNote("");
      setTurns((prev) => [...prev, makeTurn("user", clean)]);
      setEmotion("thinking");
      onStateChange("thinking");

      const ctrl = new AbortController();
      turnAbortRef.current = ctrl;

      try {
        const useReset = resetNextTurnRef.current;
        resetNextTurnRef.current = false;
        const res = await sendCompanionChat(clean, {
          resetPending: useReset,
          signal: ctrl.signal,
        });
        if (sessionEpochRef.current !== epoch) return;

        const nextEmotion = res.emotion ?? "neutral";
        setTurns((prev) => [...prev, makeTurn("assistant", res.reply, nextEmotion)]);
        setEmotion(nextEmotion);
        onStateChange("speaking");

        try {
          const wav = await synthesizeVoice(res.reply, ctrl.signal);
          if (sessionEpochRef.current !== epoch) return;
          await playWav(wav, setAudioLevel, ctrl.signal);
        } catch (ttsErr) {
          if (ctrl.signal.aborted || sessionEpochRef.current !== epoch) return;
          if (ttsErr instanceof Unauthorized) throw ttsErr;
          await speakFallback(res.reply, setAudioLevel, ctrl.signal);
        }

        if (sessionEpochRef.current !== epoch) return;
        setAudioLevel(0);

        if (res.end_conversation) {
          playChime("done");
          exitToStandby(false);
          return;
        }
        await runListenTurnRef.current(epoch, true);
      } catch (err) {
        if (ctrl.signal.aborted || sessionEpochRef.current !== epoch) return;
        if (err instanceof Unauthorized) {
          exitToStandby(false);
          onUnauthorized();
          return;
        }
        if (err instanceof BusyError) {
          setEmotion("sorry");
          setStatusNote("他のチャネルで会話中です。少し待ってから話しかけてね。");
        } else {
          setEmotion("sorry");
          setStatusNote(err instanceof Error ? err.message : "応答の取得に失敗しました");
        }
        onStateChange("idle_in_chat");
        startIdleCountdown(epoch);
      }
    },
    [clearSilenceTimer, exitToStandby, onStateChange, onUnauthorized, startIdleCountdown],
  );

  const runListenTurn = useCallback(
    async (epoch: number, isFollowUp: boolean) => {
      if (sessionEpochRef.current !== epoch) return;
      onStateChange(isFollowUp ? "idle_in_chat" : "listening");
      if (isFollowUp) {
        startIdleCountdown(epoch);
      } else {
        clearSilenceTimer();
      }

      const stream = await ensureMicStream();
      if (sessionEpochRef.current !== epoch) return;

      if (!stream) {
        setStatusNote("マイクが利用できないため、下のテキスト入力で会話できます。");
        onStateChange("idle_in_chat");
        if (!isFollowUp) {
          startIdleCountdown(epoch);
        }
        return;
      }

      const ctrl = new AbortController();
      turnAbortRef.current = ctrl;

      // For follow-up turns, startIdleCountdown enforces timeout (respecting typing pause).
      const captureTimeoutMs = isFollowUp
        ? 3_600_000
        : Math.max(settingsRef.current.silenceTimeoutSec, 12) * 1000;

      const { promise, finishNow } = startUtteranceCapture(stream, {
        noSpeechTimeoutMs: captureTimeoutMs,
        onSpeechStart: () => {
          if (sessionEpochRef.current !== epoch) return;
          clearSilenceTimer();
          setStatusNote("");
          onStateChange("listening");
        },
        onLevel: (lvl) => {
          if (sessionEpochRef.current === epoch) setAudioLevel(lvl);
        },
        signal: ctrl.signal,
      });
      finishRecRef.current = finishNow;

      const captured = await promise;
      finishRecRef.current = null;
      if (sessionEpochRef.current !== epoch) return;

      if (captured.status === "aborted") return;
      if (captured.status === "timeout") {
        exitToStandby(isFollowUp);
        return;
      }

      clearSilenceTimer();
      onStateChange("thinking");
      setEmotion("thinking");

      try {
        const transcript = await transcribeVoice(
          captured.blob,
          captured.mimeType,
          settingsRef.current.sttPrompt,
          ctrl.signal,
        );
        if (sessionEpochRef.current !== epoch) return;
        if (!transcript) {
          setStatusNote("聞き取れませんでした。もう一度どうぞ。");
          setEmotion("neutral");
          onStateChange("idle_in_chat");
          startIdleCountdown(epoch);
          return;
        }
        await submitUtterance(transcript, epoch);
      } catch (err) {
        if (ctrl.signal.aborted || sessionEpochRef.current !== epoch) return;
        if (err instanceof Unauthorized) {
          exitToStandby(false);
          onUnauthorized();
          return;
        }
        if (err instanceof ServiceUnavailableError) {
          setMicAvailable(false);
          setStatusNote("Core の音声認識 (STT) が未設定です。テキスト入力で会話できます。");
        } else {
          setStatusNote(err instanceof Error ? err.message : "音声認識に失敗しました");
        }
        setEmotion("sorry");
        onStateChange("idle_in_chat");
        startIdleCountdown(epoch);
      }
    },
    [
      clearSilenceTimer,
      ensureMicStream,
      exitToStandby,
      onStateChange,
      onUnauthorized,
      startIdleCountdown,
      submitUtterance,
    ],
  );

  runListenTurnRef.current = runListenTurn;

  const startChat = useCallback(async () => {
    const epoch = abortCurrentTurn();
    setTurns([]);
    setEmotion("happy");
    setStatusNote("");
    playChime("listen");
    await runListenTurn(epoch, false);
  }, [abortCurrentTurn, runListenTurn]);

  const finishListeningNow = useCallback(() => {
    finishRecRef.current?.();
  }, []);

  const cancelThinking = useCallback(() => {
    const epoch = abortCurrentTurn();
    void cancelChat().catch(() => {});
    setEmotion("neutral");
    setStatusNote("応答を中断しました。");
    onStateChange("idle_in_chat");
    startIdleCountdown(epoch);
  }, [abortCurrentTurn, onStateChange, startIdleCountdown]);

  const interruptSpeaking = useCallback(() => {
    const epoch = abortCurrentTurn();
    setStatusNote("");
    playChime("listen");
    void runListenTurn(epoch, false);
  }, [abortCurrentTurn, runListenTurn]);

  const listenAgain = useCallback(() => {
    const epoch = abortCurrentTurn();
    setStatusNote("");
    playChime("listen");
    void runListenTurn(epoch, false);
  }, [abortCurrentTurn, runListenTurn]);

  const submitText = useCallback(
    (text: string) => {
      const clean = text.trim();
      if (!clean) return;
      const epoch = abortCurrentTurn();
      typingActiveRef.current = false;
      void submitUtterance(clean, epoch);
    },
    [abortCurrentTurn, submitUtterance],
  );

  const setTypingActive = useCallback((active: boolean) => {
    typingActiveRef.current = active;
  }, []);

  return {
    turns,
    emotion,
    audioLevel,
    silenceLeftSec,
    micAvailable,
    statusNote,
    startChat,
    finishListeningNow,
    cancelThinking,
    interruptSpeaking,
    listenAgain,
    submitText,
    setTypingActive,
    exitToStandby,
  };
}
