import { getAudioContext } from "./audioEngine";

export type CaptureOptions = {
  speechThreshold?: number;
  silenceAfterSpeechMs?: number;
  noSpeechTimeoutMs: number;
  maxUtteranceMs?: number;
  onLevel?: (level: number) => void;
  onSpeechStart?: () => void;
  signal?: AbortSignal;
};

export type CaptureResult =
  | { status: "recorded"; blob: Blob; mimeType: string }
  | { status: "timeout" }
  | { status: "aborted" };

export function isMicSupported(): boolean {
  return Boolean(
    typeof navigator !== "undefined" &&
      typeof navigator.mediaDevices?.getUserMedia === "function" &&
      typeof MediaRecorder !== "undefined",
  );
}

export function pickSupportedAudioMimeType(): string {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
    return "";
  }
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
  ];
  for (const c of candidates) {
    if (MediaRecorder.isTypeSupported(c)) return c;
  }
  return "";
}

export async function acquireMicStream(): Promise<MediaStream> {
  if (!isMicSupported()) {
    throw new Error("この環境ではマイク入力（HTTPS または localhost）が利用できません");
  }
  return navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      channelCount: 1,
    },
  });
}

/** マイクストリームから VAD で 1 発話分を録音し、無音またはタイムアウトで終了する。 */
export function startUtteranceCapture(
  stream: MediaStream,
  opts: CaptureOptions,
): { promise: Promise<CaptureResult>; finishNow: () => void } {
  const speechThreshold = opts.speechThreshold ?? 0.032;
  const silenceAfterSpeechMs = opts.silenceAfterSpeechMs ?? 1100;
  const maxUtteranceMs = opts.maxUtteranceMs ?? 20000;

  let finishHandler = () => {};

  const promise = new Promise<CaptureResult>((resolve) => {
    if (opts.signal?.aborted) {
      resolve({ status: "aborted" });
      return;
    }

    const mimeType = pickSupportedAudioMimeType();
    const recorder = mimeType
      ? new MediaRecorder(stream, { mimeType })
      : new MediaRecorder(stream);
    const chunks: BlobPart[] = [];
    recorder.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) chunks.push(ev.data);
    };

    const ctx = getAudioContext();
    if (ctx.state === "suspended") {
      void ctx.resume();
    }
    const sourceNode = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    sourceNode.connect(analyser);
    const timeData = new Uint8Array(analyser.fftSize);

    const startedAt = performance.now();
    let speechStarted = false;
    let activeFrames = 0;
    let speechStartedAt = 0;
    let lastSpeechAt = 0;
    let rafId = 0;
    let finalizing = false;
    let outcome: "recorded" | "timeout" | "aborted" = "aborted";

    const cleanupAudio = () => {
      if (rafId) cancelAnimationFrame(rafId);
      opts.signal?.removeEventListener("abort", onAbort);
      try {
        sourceNode.disconnect();
        analyser.disconnect();
      } catch {
        // ignore
      }
      opts.onLevel?.(0);
    };

    const finalize = (mode: "recorded" | "timeout" | "aborted") => {
      if (finalizing) return;
      finalizing = true;
      outcome = mode;
      cleanupAudio();

      if (recorder.state !== "inactive") {
        recorder.onstop = () => {
          if (outcome === "recorded") {
            const actualMime = recorder.mimeType || mimeType || "audio/webm";
            const blob = new Blob(chunks, { type: actualMime });
            if (blob.size === 0) {
              resolve({ status: "timeout" });
            } else {
              resolve({ status: "recorded", blob, mimeType: actualMime });
            }
          } else {
            resolve({ status: outcome });
          }
        };
        try {
          recorder.stop();
        } catch {
          resolve({ status: outcome === "aborted" ? "aborted" : "timeout" });
        }
      } else if (outcome === "recorded") {
        const actualMime = recorder.mimeType || mimeType || "audio/webm";
        const blob = new Blob(chunks, { type: actualMime });
        resolve(blob.size > 0 ? { status: "recorded", blob, mimeType: actualMime } : { status: "timeout" });
      } else {
        resolve({ status: outcome });
      }
    };

    const onAbort = () => finalize("aborted");
    opts.signal?.addEventListener("abort", onAbort, { once: true });

    finishHandler = () => {
      if (finalizing) return;
      if (speechStarted || chunks.length > 0) {
        finalize("recorded");
      } else {
        finalize("timeout");
      }
    };

    const loop = () => {
      if (finalizing) return;
      analyser.getByteTimeDomainData(timeData);
      let sum = 0;
      for (let i = 0; i < timeData.length; i++) {
        const v = (timeData[i] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / timeData.length);
      opts.onLevel?.(Math.min(1, rms * 4.0));

      const now = performance.now();
      if (!speechStarted) {
        if (rms >= speechThreshold) {
          activeFrames += 1;
          if (activeFrames >= 2) {
            speechStarted = true;
            speechStartedAt = now;
            lastSpeechAt = now;
            opts.onSpeechStart?.();
          }
        } else {
          activeFrames = 0;
        }
        if (!speechStarted && now - startedAt >= opts.noSpeechTimeoutMs) {
          finalize("timeout");
          return;
        }
      } else {
        if (rms >= speechThreshold) {
          lastSpeechAt = now;
        } else if (
          now - lastSpeechAt >= silenceAfterSpeechMs &&
          now - speechStartedAt >= 350
        ) {
          finalize("recorded");
          return;
        }
        if (now - speechStartedAt >= maxUtteranceMs) {
          finalize("recorded");
          return;
        }
      }

      rafId = requestAnimationFrame(loop);
    };

    try {
      recorder.start(200);
    } catch {
      recorder.start();
    }
    rafId = requestAnimationFrame(loop);
  });

  return {
    promise,
    finishNow: () => finishHandler(),
  };
}
