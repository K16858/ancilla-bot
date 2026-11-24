export type CompanionState =
  | "uninitialized"
  | "standby"
  | "listening"
  | "thinking"
  | "speaking"
  | "idle_in_chat"
  | "alerting";

export type Emotion =
  | "neutral"
  | "happy"
  | "smile"
  | "calm"
  | "surprised"
  | "thinking"
  | "sorry"
  | "alert"
  | (string & {});

export type TimerStatus = "running" | "firing" | "stopped" | "cancelled";

export type TimerItem = {
  id: string;
  label: string;
  duration_sec: number;
  status: TimerStatus;
  created_at: string;
  ends_at: string;
  fired_at: string | null;
  stopped_at: string | null;
  source: string;
  remaining_sec: number;
};

export type TimersPayload = {
  server_now: string;
  timers: TimerItem[];
};

export type NotificationItem = {
  id: number;
  created_at: string;
  source: string;
  category: string;
  level: string;
  title: string | null;
  message: string;
  detail: string | null;
};

export type CompanionChatResponse = {
  reply: string;
  emotion: Emotion | null;
  end_conversation: boolean;
  session_id: string;
};

export type SessionEndResponse = {
  ok: boolean;
  ended: boolean;
  session_id: string;
};

export type DndSettings = {
  manualEnabled: boolean;
  scheduleEnabled: boolean;
  startTime: string;
  endTime: string;
  silenceTimeoutSec: number;
  sttPrompt: string;
  muteNotificationSound: boolean;
};

export type ConnState = "connecting" | "open" | "retrying";

export type Me = {
  name: string;
  role: "read" | "operate";
};

export type SubtitleTurn = {
  id: string;
  role: "user" | "assistant";
  text: string;
  emotion?: Emotion | null;
  at: number;
};

export type AlertContext =
  | { kind: "timer"; timers: TimerItem[] }
  | { kind: "notification"; notification: NotificationItem };
