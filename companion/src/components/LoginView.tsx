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
      <section className="card-panel">
        <h1>Ancilla Companion</h1>
        <p className="muted">
          Core API の Bearer トークンを入力して接続します。
        </p>
        <form onSubmit={handleSubmit} className="login-form">
          <input
            type="password"
            className="text-input"
            placeholder="Bearer トークン"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            autoComplete="current-password"
            disabled={busy}
          />
          <button type="submit" className="primary-btn" disabled={busy}>
            {busy ? "確認中..." : "接続する"}
          </button>
        </form>
        {error && <p className="error-text">{error}</p>}
        <div className="hint-box">
          <div className="muted">音声会話・タイマー操作には operate トークンが必要です:</div>
          <code>ancilla api token create companion --role operate</code>
        </div>
      </section>
    </main>
  );
}
