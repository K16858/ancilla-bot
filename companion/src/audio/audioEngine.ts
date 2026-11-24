type WindowWithWebkitAudio = Window & {
  webkitAudioContext?: typeof AudioContext;
};

let sharedCtx: AudioContext | null = null;
let activePlaybackStop: (() => void) | null = null;

export function getAudioContext(): AudioContext {
  if (!sharedCtx) {
    const AudioCtx =
      window.AudioContext ?? (window as WindowWithWebkitAudio).webkitAudioContext;
    if (!AudioCtx) {
      throw new Error("このブラウザは Web Audio API に対応していません");
    }
    sharedCtx = new AudioCtx();
  }
  return sharedCtx;
}

async function resumeWithTimeout(ctx: AudioContext, ms = 350): Promise<void> {
  if (ctx.state !== "suspended") return;
  await Promise.race([
    ctx.resume().catch(() => {}),
    new Promise<void>((resolve) => window.setTimeout(resolve, ms)),
  ]);
}

/** ユーザータップ内で呼び出し、iOS Safari / Android Chrome の自動再生制限を解除する。 */
export async function unlockAudio(): Promise<void> {
  try {
    const ctx = getAudioContext();
    await resumeWithTimeout(ctx);
    const buffer = ctx.createBuffer(1, 1, 22050);
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(ctx.destination);
    src.start(0);
  } catch {
    // ignore if audio output is unavailable or already unlocked
  }
}

export function stopAllPlayback(): void {
  activePlaybackStop?.();
  activePlaybackStop = null;
}

/** Core TTS の WAV バイナリをデコード再生し、AnalyserNode の音量を onLevel へ流す。 */
export async function playWav(
  wavBytes: ArrayBuffer,
  onLevel: (level: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  if (signal?.aborted) return;
  stopAllPlayback();

  const ctx = getAudioContext();
  await resumeWithTimeout(ctx);
  const audioBuf = await ctx.decodeAudioData(wavBytes.slice(0));
  if (signal?.aborted) return;

  await new Promise<void>((resolve) => {
    const source = ctx.createBufferSource();
    source.buffer = audioBuf;
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    const data = new Uint8Array(analyser.fftSize);

    source.connect(analyser);
    analyser.connect(ctx.destination);

    let rafId = 0;
    let settled = false;

    const cleanup = () => {
      if (settled) return;
      settled = true;
      if (rafId) cancelAnimationFrame(rafId);
      signal?.removeEventListener("abort", onAbort);
      try {
        source.stop();
      } catch {
        // already stopped
      }
      try {
        source.disconnect();
        analyser.disconnect();
      } catch {
        // ignore disconnect errors
      }
      if (activePlaybackStop === onAbort) {
        activePlaybackStop = null;
      }
      onLevel(0);
      resolve();
    };

    const onAbort = () => cleanup();
    activePlaybackStop = onAbort;
    signal?.addEventListener("abort", onAbort, { once: true });

    const tick = () => {
      if (settled) return;
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / data.length);
      onLevel(Math.min(1, rms * 3.6));
      rafId = requestAnimationFrame(tick);
    };

    source.onended = () => cleanup();
    source.start(0);
    rafId = requestAnimationFrame(tick);
  });
}

/** Core TTS 未設定（503）時の Web Speech API 読み上げフォールバック。 */
export async function speakFallback(
  text: string,
  onLevel: (level: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  const clean = text.trim();
  if (!clean || signal?.aborted || typeof window === "undefined" || !("speechSynthesis" in window)) {
    return;
  }
  stopAllPlayback();

  await new Promise<void>((resolve) => {
    const synth = window.speechSynthesis;
    const utter = new SpeechSynthesisUtterance(clean);
    utter.lang = "ja-JP";
    const voices = synth.getVoices();
    const jaVoice = voices.find((v) => v.lang.toLowerCase().startsWith("ja"));
    if (jaVoice) utter.voice = jaVoice;

    let phase = 0;
    let settled = false;

    const cleanup = () => {
      if (settled) return;
      settled = true;
      clearInterval(pulseTimer);
      clearTimeout(guardTimer);
      signal?.removeEventListener("abort", onAbort);
      if (activePlaybackStop === onAbort) {
        activePlaybackStop = null;
      }
      onLevel(0);
      resolve();
    };

    const onAbort = () => {
      try {
        synth.cancel();
      } catch {
        // ignore
      }
      cleanup();
    };

    activePlaybackStop = onAbort;
    signal?.addEventListener("abort", onAbort, { once: true });

    const pulseTimer = window.setInterval(() => {
      phase += 0.7;
      onLevel(0.28 + 0.25 * Math.abs(Math.sin(phase)));
    }, 90);

    const guardTimer = window.setTimeout(cleanup, Math.max(4500, clean.length * 260));
    utter.onend = () => cleanup();
    utter.onerror = () => cleanup();

    try {
      synth.cancel();
      synth.speak(utter);
    } catch {
      cleanup();
    }
  });
}

function playTone(
  ctx: AudioContext,
  freq: number,
  startOffsetSec: number,
  durationSec: number,
  peakGain = 0.08,
): void {
  const start = ctx.currentTime + startOffsetSec;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = "sine";
  osc.frequency.setValueAtTime(freq, start);
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(peakGain, start + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + durationSec);
  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.start(start);
  osc.stop(start + durationSec + 0.02);
}

/** UI 操作・通知用の短いチャイム音を鳴らす。 */
export function playChime(kind: "listen" | "notify" | "done"): void {
  try {
    const ctx = getAudioContext();
    if (ctx.state === "suspended") {
      void ctx.resume();
    }
    if (kind === "listen") {
      playTone(ctx, 587.33, 0, 0.09, 0.07);
      playTone(ctx, 880, 0.08, 0.14, 0.07);
    } else if (kind === "notify") {
      playTone(ctx, 659.25, 0, 0.12, 0.06);
      playTone(ctx, 987.77, 0.11, 0.18, 0.06);
    } else {
      playTone(ctx, 659.25, 0, 0.1, 0.05);
      playTone(ctx, 440, 0.09, 0.16, 0.05);
    }
  } catch {
    // ignore before unlock
  }
}

/** タイマー満了時のループアラームを開始し、停止関数を返す。 */
export function startAlarmLoop(): () => void {
  let stopped = false;

  const ringOnce = () => {
    if (stopped) return;
    try {
      const ctx = getAudioContext();
      if (ctx.state === "suspended") {
        void ctx.resume();
      }
      playTone(ctx, 880, 0, 0.16, 0.12);
      playTone(ctx, 1174.66, 0.18, 0.18, 0.12);
      playTone(ctx, 880, 0.42, 0.16, 0.11);
      playTone(ctx, 1174.66, 0.6, 0.24, 0.12);
    } catch {
      // ignore
    }
  };

  ringOnce();
  const id = window.setInterval(ringOnce, 1600);
  return () => {
    stopped = true;
    clearInterval(id);
  };
}
