export type WakeWordDetection = {
  keyword: string;
  detectedAt: number;
};

/** Step 4 (Silero VAD+STT / openWakeWord ONNX) で差し替えるウェイクワード検出抽象。 */
export interface WakeWordEngine {
  readonly name: string;
  readonly supported: boolean;
  start(stream: MediaStream, onDetected: (hit: WakeWordDetection) => void): Promise<void>;
  stop(): Promise<void>;
}

/** 初期版（タップ起動）用の No-op 実装。 */
export class NoopWakeWordEngine implements WakeWordEngine {
  readonly name = "noop";
  readonly supported = false;

  async start(_stream: MediaStream, _onDetected: (hit: WakeWordDetection) => void): Promise<void> {
    // Step 4 で実装を差し替える
  }

  async stop(): Promise<void> {
    // no-op
  }
}
