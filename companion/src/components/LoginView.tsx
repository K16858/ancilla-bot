import { useState, type FormEvent } from "react";
import { fetchMe, setToken, Unauthorized } from "../api";
import type { Me } from "../types";

type LoginViewProps = {
  onLoggedIn: (me: Me) => void;
};

export function LoginView({ onLoggedIn }: LoginViewProps) {
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const token = input.trim();
    if (!token) {
      setError("Bearer トークンを入力してください");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const me = await fetchMe(token);
      setToken(token);
      onLoggedIn(me);
    } catch (err) {
      if (err instanceof Unauthorized) {
        setError("トークンが無効または失効しています。もう一度確認してください。");
      } else {
        setError(err instanceof Error ? err.message : "接続に失敗しました");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="companion-shell">
      <section className="card-panel login-panel">
        <header className="panel-head">
          <h1>Ancilla Companion</h1>
          <p className="muted">
            Core API の Bearer トークンでコンパニオン端末を接続します。
          </p>
        </header>
        <form onSubmit={handleSubmit} className="login-form">
          <div className="field-block">
            <label htmlFor="companion-token" className="field-label">
              アクセストークン
            </label>
            <input
              id="companion-token"
              type="password"
              className="text-input"
              placeholder="トークン文字列を貼り付け"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              autoComplete="current-password"
              disabled={busy}
            />
          </div>
          <p className="field-helper error-text" role={error ? "alert" : undefined}>
            {error}
          </p>
          <button type="submit" className="primary-btn" disabled={busy}>
            {busy ? "確認中…" : "接続する"}
          </button>
        </form>
        <div className="panel-footer-note">
          <p className="muted">音声会話・タイマー操作には operate トークンが必要です。</p>
          <code>ancilla api token create companion --role operate</code>
        </div>
      </section>
    </main>
  );
}
