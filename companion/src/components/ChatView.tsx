import { useEffect, useRef, useState, type FormEvent } from "react";
import type { CompanionState, Emotion, SubtitleTurn } from "../types";
import { AvatarView } from "./AvatarView";

type ChatViewProps = {
  state: CompanionState;
  emotion: Emotion | null;
  audioLevel: number;
  turns: SubtitleTurn[];
  silenceLeftSec: number | null;
  silenceTimeoutSec: number;
  micAvailable: boolean;
  statusNote: string;
  onFinishSpeakingNow: () => void;
  onCancelThinking: () => void;
  onInterruptSpeaking: () => void;
  onListenAgain: () => void;
  onSubmitText: (text: string) => void;
  onTypingActiveChange: (active: boolean) => void;
  onEndConversation: () => void;
};

function stateLabel(state: CompanionState, silenceLeftSec: number | null): string {
  switch (state) {
    case "listening":
      return "聞いています…";
    case "thinking":
      return "考え中…";
    case "speaking":
      return "お話し中…";
    case "idle_in_chat":
      return silenceLeftSec !== null
        ? `続けて話せます（あと ${silenceLeftSec} 秒）`
        : "待機中";
    default:
      return "会話中";
  }
}

export function ChatView({
  state,
  emotion,
  audioLevel,
  turns,
  silenceLeftSec,
  silenceTimeoutSec,
  micAvailable,
  statusNote,
  onFinishSpeakingNow,
  onCancelThinking,
  onInterruptSpeaking,
  onListenAgain,
  onSubmitText,
  onTypingActiveChange,
  onEndConversation,
}: ChatViewProps) {
  const [textInput, setTextInput] = useState("");
  const [showKeyboard, setShowKeyboard] = useState<boolean>(() => !micAvailable);
  const [inputFocused, setInputFocused] = useState<boolean>(false);
  const subtitleEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!micAvailable) setShowKeyboard(true);
  }, [micAvailable]);

  useEffect(() => {
    subtitleEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  useEffect(() => {
    onTypingActiveChange(inputFocused || textInput.trim().length > 0);
  }, [inputFocused, textInput, onTypingActiveChange]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const val = textInput.trim();
    if (!val) return;
    setTextInput("");
    onTypingActiveChange(false);
    onSubmitText(val);
  };

  const recentTurns = turns.slice(-6);
  const progressPct =
    silenceLeftSec !== null && silenceTimeoutSec > 0
      ? Math.max(0, Math.min(100, (silenceLeftSec / silenceTimeoutSec) * 100))
      : 0;

  return (
    <main className="companion-shell chat-shell">
      <header className="top-bar">
        <span className={`state-pill state-${state}`}>
          {stateLabel(state, silenceLeftSec)}
        </span>
        <button type="button" className="icon-btn" onClick={onEndConversation}>
          会話を終える
        </button>
      </header>

      <section className="chat-stage">
        <AvatarView state={state} emotion={emotion} audioLevel={audioLevel} />

        {recentTurns.length > 0 && (
          <div className="subtitles-box" aria-live="polite">
            {recentTurns.map((t) => (
              <div key={t.id} className={`subtitle-row role-${t.role}`}>
                <span className="subtitle-speaker">
                  {t.role === "user" ? "あなた" : "Ancilla"}
                </span>
                <p className="subtitle-text">{t.text}</p>
              </div>
            ))}
            <div ref={subtitleEndRef} />
          </div>
        )}

        {statusNote && <p className="status-note">{statusNote}</p>}
      </section>

      <footer className="chat-footer">
        {state === "idle_in_chat" && silenceLeftSec !== null && (
          <div className="silence-bar-wrap" aria-label="無言タイムアウト計測">
            <div className="silence-bar-fill" style={{ width: `${progressPct}%` }} />
          </div>
        )}

        <div className="chat-controls">
          {state === "listening" && (
            <button type="button" className="primary-btn" onClick={onFinishSpeakingNow}>
              話し終わった
            </button>
          )}
          {state === "thinking" && (
            <button type="button" className="ghost-btn danger-outline" onClick={onCancelThinking}>
              中断する
            </button>
          )}
          {state === "speaking" && (
            <button type="button" className="primary-btn" onClick={onInterruptSpeaking}>
              割り込んで話す
            </button>
          )}
          {state === "idle_in_chat" && micAvailable && (
            <button type="button" className="primary-btn" onClick={onListenAgain}>
              話す
            </button>
          )}
          <button
            type="button"
            className="icon-btn"
            onClick={() => setShowKeyboard((v) => !v)}
          >
            {showKeyboard ? "キーボードを隠す" : "文字で入力"}
          </button>
        </div>

        {showKeyboard && (
          <form className="text-fallback-form" onSubmit={handleSubmit}>
            <input
              type="text"
              className="text-input"
              placeholder="メッセージを入力して送信…"
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
              onFocus={() => setInputFocused(true)}
              onBlur={() => setInputFocused(false)}
              disabled={state === "thinking"}
            />
            <button
              type="submit"
              className="primary-btn"
              disabled={!textInput.trim() || state === "thinking"}
            >
              送信
            </button>
          </form>
        )}
      </footer>
    </main>
  );
}
