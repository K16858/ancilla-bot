import type { CompanionState, Emotion } from "../types";

type AvatarViewProps = {
  state: CompanionState;
  emotion?: Emotion | null;
  audioLevel: number;
  statusText?: string;
};

function isHappy(emotion?: Emotion | null): boolean {
  return emotion === "happy" || emotion === "smile";
}

function isSorry(emotion?: Emotion | null): boolean {
  return emotion === "sorry";
}

export function AvatarView({ state, emotion, audioLevel, statusText }: AvatarViewProps) {
  const level = Math.max(0, Math.min(1, audioLevel));
  const mouthRy = state === "speaking" ? 2.5 + level * 11 : emotion === "surprised" ? 6 : 2;
  const ringScale = 1 + (state === "listening" || state === "speaking" ? level * 0.14 : 0);

  const haloColor =
    state === "alerting"
      ? "#fb7185"
      : state === "thinking"
        ? "#a78bfa"
        : state === "speaking"
          ? "#38bdf8"
          : "#7dd3fc";

  return (
    <div className={`avatar-wrap state-${state}`}>
      <div
        className="avatar-stage"
        style={{ transform: `scale(${ringScale.toFixed(3)})` }}
      >
        <svg
          className="avatar-svg"
          viewBox="0 0 240 240"
          role="img"
          aria-label="Ancilla avatar"
        >
          <defs>
            <radialGradient id="avatarAura" cx="50%" cy="48%" r="50%">
              <stop offset="0%" stopColor={haloColor} stopOpacity="0.34" />
              <stop offset="72%" stopColor={haloColor} stopOpacity="0.08" />
              <stop offset="100%" stopColor={haloColor} stopOpacity="0" />
            </radialGradient>
            <linearGradient id="headStroke" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor={haloColor} />
              <stop offset="100%" stopColor="#a78bfa" />
            </linearGradient>
          </defs>

          <circle cx="120" cy="124" r="108" fill="url(#avatarAura)" />

          {state === "listening" && (
            <>
              <circle className="wave-ring" cx="120" cy="124" r="82" stroke="#7dd3fc" strokeWidth="2" fill="none" />
              <circle className="wave-ring delay" cx="120" cy="124" r="92" stroke="#7dd3fc" strokeWidth="1.5" fill="none" />
            </>
          )}

          {state === "alerting" && (
            <circle className="alert-ring" cx="120" cy="124" r="86" stroke="#fb7185" strokeWidth="3" fill="none" />
          )}

          {/* Cat ears (kemomimi silhouette) */}
          <path
            d="M66 96 L52 40 L102 72 Z"
            fill="#172342"
            stroke="url(#headStroke)"
            strokeWidth="3.5"
            strokeLinejoin="round"
          />
          <path
            d="M174 96 L188 40 L138 72 Z"
            fill="#172342"
            stroke="url(#headStroke)"
            strokeWidth="3.5"
            strokeLinejoin="round"
          />
          <path d="M71 86 L62 55 L92 74 Z" fill="#f472b6" opacity="0.58" />
          <path d="M169 86 L178 55 L148 74 Z" fill="#f472b6" opacity="0.58" />

          {/* Maid headband & center ribbon */}
          <path d="M84 72 Q120 58 156 72" stroke="#f8fafc" strokeWidth="6" strokeLinecap="round" fill="none" />
          <path d="M108 64 L120 69 L132 64 L120 58 Z" fill="#f472b6" />
          <circle cx="120" cy="64" r="4" fill="#fbcfe8" />

          {/* Face circle */}
          <circle
            cx="120"
            cy="128"
            r="60"
            fill="#141e38"
            stroke="url(#headStroke)"
            strokeWidth="3.5"
          />

          {/* Soft bangs */}
          <path
            d="M68 112 Q86 80 120 84 Q154 80 172 112 Q150 96 134 106 Q120 94 106 106 Q90 96 68 112 Z"
            fill="#1e2d54"
            opacity="0.9"
          />

          {/* Blush */}
          <ellipse
            cx="84"
            cy="138"
            rx="9"
            ry="4.5"
            fill="#f472b6"
            opacity={isHappy(emotion) ? "0.45" : "0.24"}
          />
          <ellipse
            cx="156"
            cy="138"
            rx="9"
            ry="4.5"
            fill="#f472b6"
            opacity={isHappy(emotion) ? "0.45" : "0.24"}
          />

          {/* Brows */}
          {isSorry(emotion) ? (
            <>
              <path d="M86 108 L104 104" stroke="#cbd5e1" strokeWidth="2.5" strokeLinecap="round" />
              <path d="M154 108 L136 104" stroke="#cbd5e1" strokeWidth="2.5" strokeLinecap="round" />
            </>
          ) : state === "thinking" ? (
            <>
              <path d="M86 106 Q96 101 105 106" stroke="#cbd5e1" strokeWidth="2.5" strokeLinecap="round" fill="none" />
              <path d="M135 104 L154 104" stroke="#cbd5e1" strokeWidth="2.5" strokeLinecap="round" />
            </>
          ) : null}

          {/* Eyes */}
          {isHappy(emotion) ? (
            <>
              <path d="M86 125 Q96 115 106 125" stroke="#7dd3fc" strokeWidth="4" strokeLinecap="round" fill="none" />
              <path d="M134 125 Q144 115 154 125" stroke="#7dd3fc" strokeWidth="4" strokeLinecap="round" fill="none" />
            </>
          ) : (
            <>
              <ellipse cx="96" cy="124" rx="8" ry={emotion === "surprised" ? 10 : 8.5} fill="#7dd3fc" />
              <ellipse cx="144" cy="124" rx="8" ry={emotion === "surprised" ? 10 : 8.5} fill="#7dd3fc" />
              <circle cx="99" cy="120.5" r="2.6" fill="#ffffff" />
              <circle cx="147" cy="120.5" r="2.6" fill="#ffffff" />
            </>
          )}

          {/* Mouth */}
          {state === "speaking" || emotion === "surprised" ? (
            <ellipse
              cx="120"
              cy="151"
              rx={state === "speaking" ? 8 + level * 4 : 6}
              ry={mouthRy}
              fill="#fb7185"
              stroke="#f8fafc"
              strokeWidth="2"
            />
          ) : isSorry(emotion) ? (
            <path d="M111 153 Q120 147 129 153" stroke="#e2e8f0" strokeWidth="3.2" strokeLinecap="round" fill="none" />
          ) : (
            <path d="M108 148 Q120 158 132 148" stroke="#e2e8f0" strokeWidth="3.2" strokeLinecap="round" fill="none" />
          )}

          {/* Thinking dots */}
          {state === "thinking" && (
            <g className="think-dots" fill="#c4b5fd">
              <circle cx="174" cy="76" r="4" />
              <circle cx="188" cy="64" r="5" />
              <circle cx="204" cy="52" r="6" />
            </g>
          )}
        </svg>
      </div>
      {statusText && <p className="avatar-status">{statusText}</p>}
    </div>
  );
}
