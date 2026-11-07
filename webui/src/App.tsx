import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import {
  Unauthorized, clearToken, get, getToken, setToken, stream,
  type Conn, type Evidence, type Host, type Incident, type IncidentDetail, type NodeInfo, type Service, type Summary,
} from "./api";

type Ctx = { rev: number; now: number; logout: () => void };
const Ctx = createContext<Ctx>({ rev: 0, now: 0, logout: () => {} });

// ---- 共通部品 ----

function useGet<T>(path: string) {
  const { rev, logout } = useContext(Ctx);
  const [state, setState] = useState<{ path: string; data?: T; error?: string }>({ path });
  useEffect(() => {
    const ac = new AbortController();
    get<T>(path, ac.signal)
      .then((data) => setState({ path, data }))
      .catch((e) => {
        if (ac.signal.aborted) return;
        if (e instanceof Unauthorized) logout();
        else setState((s) => ({ path, data: s.path === path ? s.data : undefined, error: String(e.message ?? e) }));
      });
    return () => ac.abort();
  }, [path, rev, logout]);
  return state.path === path ? state : { path };
}

function Async<T>({ r, children }: { r: { data?: T; error?: string }; children: (d: T) => ReactNode }) {
  if (r.error && !r.data) return <p role="alert" className="err">読み込めませんでした: {r.error}</p>;
  if (!r.data) return <p>読み込み中…</p>;
  return (
    <>
      {r.error && <p role="alert" className="err">更新に失敗しました: {r.error}</p>}
      {children(r.data)}
    </>
  );
}

const UNITS: [number, string][] = [[86400, "日"], [3600, "時間"], [60, "分"]];

function relative(ms: number): string {
  const s = Math.round(Math.abs(ms) / 1000);
  const [n, u] = UNITS.find(([n]) => s >= n) ?? [1, "秒"];
  return `${Math.floor(s / n)}${u}${ms < 0 ? "後" : "前"}`;
}

/** 観測時刻。相対表示 + title に絶対時刻。 */
function Time({ at, label }: { at?: string | null; label?: string }) {
  const { now } = useContext(Ctx);
  if (!at) return <span className="dim">{label}時刻なし</span>;
  const t = new Date(at).getTime();
  return (
    <time dateTime={at} title={at} className="time">
      {label}{Number.isNaN(t) ? at : relative(now - t)}
    </time>
  );
}

const STATE: Record<string, [string, string]> = {
  healthy: ["✔", "正常"], degraded: ["▲", "劣化"], unhealthy: ["✖", "異常"], unknown: ["?", "不明"],
};
function State({ s }: { s: string }) {
  const [icon, word] = STATE[s] ?? ["?", s];
  return (
    <span className={`badge s-${STATE[s] ? s : "unknown"}`}>
      <span aria-hidden="true">{icon} </span>{word}<span className="dim"> ({s})</span>
    </span>
  );
}

const SEV: Record<string, string> = { critical: "重大", high: "高", warning: "警告", medium: "中", low: "低", info: "情報" };
const INC_STATUS: Record<string, string> = { open: "未対応", acknowledged: "確認済み", resolved: "解決済み" };
function Sev({ s }: { s: string }) {
  return <span className={`badge sev-${s}`}>{SEV[s] ?? s}<span className="dim"> ({s})</span></span>;
}
function IncStatus({ s }: { s: string }) {
  return <span className={`badge i-${s}`}>{INC_STATUS[s] ?? s}</span>;
}

const link = (kind: string, id: string) => <a href={`#/${kind}/${encodeURIComponent(id)}`}>{id}</a>;
const text = (v: unknown) => (v !== null && typeof v === "object" ? JSON.stringify(v) : String(v));

function KV({ o }: { o: Record<string, unknown> }) {
  return (
    <dl className="kv">
      {Object.entries(o).map(([k, v]) => (
        <div key={k}><dt>{k}</dt><dd>{text(v)}</dd></div>
      ))}
    </dl>
  );
}

function Metrics({ values }: { values: unknown }) {
  const v = values as { resources?: Record<string, unknown>; disks?: Record<string, unknown>[] } | null;
  if (!v || typeof v !== "object") return null;
  const disks = Array.isArray(v.disks) ? v.disks : [];
  const cols = [...new Set(disks.flatMap((d) => Object.keys(d)))];
  return (
    <>
      {v.resources && <KV o={v.resources} />}
      {disks.length > 0 && (
        <table>
          <caption>ディスク</caption>
          <thead><tr>{cols.map((c) => <th key={c} scope="col">{c}</th>)}</tr></thead>
          <tbody>
            {disks.map((d, i) => <tr key={i}>{cols.map((c) => <td key={c}>{d[c] === undefined ? "" : text(d[c])}</td>)}</tr>)}
          </tbody>
        </table>
      )}
    </>
  );
}

function EvidenceList({ ev, metrics }: { ev: Evidence[]; metrics?: boolean }) {
  if (!ev.length) return <p className="dim">証拠なし</p>;
  return (
    <ul className="plain">
      {ev.map((e, i) => {
        const asMetrics = metrics && e.source === "node" && e.values;
        return (
          <li key={i} className="card">
            <strong>{e.source}</strong>{" "}
            <span className="badge">{e.freshness === "fresh" ? "新しい (fresh)" : e.freshness === "missing" ? "なし (missing)" : e.freshness}</span>{" "}
            <Time at={e.observed_at} label="観測: " />
            {asMetrics ? <Metrics values={e.values} /> : e.values != null && <pre>{JSON.stringify(e.values, null, 2)}</pre>}
          </li>
        );
      })}
    </ul>
  );
}

function Back({ to, label }: { to: string; label: string }) {
  return <p><a href={`#/${to}`}>← {label}</a></p>;
}

// ---- 画面 ----

function Overview() {
  const r = useGet<Summary>("/summary");
  return (
    <Async r={r}>
      {(s) => {
        const row = (title: string, m: Record<string, number>, href: string) => (
          <section className="card" aria-label={title}>
            <h2><a href={href}>{title}</a></h2>
            <ul className="plain counts">
              {["healthy", "degraded", "unhealthy", "unknown"].map((k) => (
                <li key={k}><State s={k} /> <strong>{m[k] ?? 0}</strong></li>
              ))}
            </ul>
          </section>
        );
        const total = Object.values(s.open_incidents).reduce((a, b) => a + b, 0);
        return (
          <>
            <p className="dim">評価時刻: <Time at={s.evaluated_at} /></p>
            <div className="grid">
              {row("Host", s.hosts, "#/hosts")}
              {row("Service", s.services, "#/services")}
              <section className="card" aria-label="未解決 Incident">
                <h2><a href="#/incidents">未解決 Incident</a></h2>
                <p><strong>{total}</strong> 件</p>
                <ul className="plain counts">
                  {Object.entries(s.open_incidents).map(([k, n]) => <li key={k}><Sev s={k} /> <strong>{n}</strong></li>)}
                </ul>
              </section>
            </div>
          </>
        );
      }}
    </Async>
  );
}

function HostList() {
  const r = useGet<Host[]>("/hosts");
  return (
    <Async r={r}>
      {(hs) => (
        <table>
          <thead>
            <tr><th scope="col">Host</th><th scope="col">状態</th><th scope="col">フラグ</th><th scope="col">OS</th><th scope="col">重要度</th><th scope="col">評価</th></tr>
          </thead>
          <tbody>
            {hs.map((h) => (
              <tr key={h.id}>
                <th scope="row">{link("hosts", h.id)} <span className="dim">{h.name}</span></th>
                <td><State s={h.status.state} /></td>
                <td>{h.status.flags.map((f) => <span key={f} className="badge flag">⚑ {f}</span>)}</td>
                <td>{h.os}</td><td>{h.criticality}</td>
                <td><Time at={h.evaluated_at} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Async>
  );
}

function HostDetail({ id }: { id: string }) {
  const r = useGet<Host>(`/hosts/${encodeURIComponent(id)}`);
  const sv = useGet<Service[]>("/services");
  return (
    <>
      <Back to="hosts" label="Host 一覧" />
      <Async r={r}>
        {(h) => (
          <>
            <h2>{h.name} <span className="dim">{h.id}</span></h2>
            <p>
              <State s={h.status.state} /> {h.status.flags.map((f) => <span key={f} className="badge flag">⚑ {f}</span>)}{" "}
              <Time at={h.evaluated_at} label="評価: " />
            </p>
            <KV o={{ os: h.os, role: h.role, criticality: h.criticality, address: h.address, node: h.node }} />
            <h3>最新メトリクス・証拠</h3>
            <EvidenceList ev={h.status.evidence} metrics />
            <h3>Service</h3>
            <Async r={sv}>
              {(all) => {
                const mine = all.filter((s) => (h.services ?? []).includes(s.id));
                return mine.length ? (
                  <ul className="plain">
                    {mine.map((s) => (
                      <li key={s.id}>{link("services", s.id)} <State s={s.status.state} /> <Time at={s.evaluated_at} label="評価: " /></li>
                    ))}
                  </ul>
                ) : <p className="dim">なし</p>;
              }}
            </Async>
          </>
        )}
      </Async>
    </>
  );
}

function ServiceList() {
  const r = useGet<Service[]>("/services");
  return (
    <Async r={r}>
      {(ss) => (
        <table>
          <thead>
            <tr><th scope="col">Service</th><th scope="col">状態</th><th scope="col">Host</th><th scope="col">種別</th><th scope="col">重要度</th><th scope="col">評価</th></tr>
          </thead>
          <tbody>
            {ss.map((s) => (
              <tr key={s.id}>
                <th scope="row">{link("services", s.id)} <span className="dim">{s.name}</span></th>
                <td><State s={s.status.state} /></td>
                <td>{link("hosts", s.host)}</td><td>{s.kind}</td><td>{s.criticality}</td>
                <td><Time at={s.evaluated_at} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Async>
  );
}

function ServiceDetail({ id }: { id: string }) {
  const r = useGet<Service>(`/services/${encodeURIComponent(id)}`);
  const ids = (xs: string[]) =>
    xs.length ? <ul className="plain">{xs.map((x) => <li key={x}>{link("services", x)}</li>)}</ul> : <p className="dim">なし</p>;
  return (
    <>
      <Back to="services" label="Service 一覧" />
      <Async r={r}>
        {(s) => (
          <>
            <h2>{s.name} <span className="dim">{s.id}</span></h2>
            <p><State s={s.status.state} /> <Time at={s.evaluated_at} label="評価: " /></p>
            <KV o={{ kind: s.kind, unit: s.unit, health_url: s.health_url, criticality: s.criticality }} />
            <p>Host: {link("hosts", s.host)}</p>
            {s.status.mismatches.length > 0 && (
              <><h3>不整合</h3><ul>{s.status.mismatches.map((m, i) => <li key={i}>{m}</li>)}</ul></>
            )}
            <h3>証拠</h3>
            <EvidenceList ev={s.status.evidence} />
            <div className="grid">
              <section><h3>依存先（動くために必要）</h3>{ids(s.impact?.dependencies ?? [])}</section>
              <section><h3>依存元（止まると影響を受ける）</h3>{ids(s.impact?.dependents ?? [])}</section>
            </div>
          </>
        )}
      </Async>
    </>
  );
}

function IncidentList() {
  const [all, setAll] = useState(false);
  const r = useGet<Incident[]>(`/incidents${all ? "?all=1" : ""}`);
  return (
    <>
      <label><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> 解決済みも表示</label>
      <Async r={r}>
        {(xs) => xs.length === 0 ? <p>該当する Incident はありません。</p> : (
          <table>
            <thead>
              <tr><th scope="col">ID</th><th scope="col">状態</th><th scope="col">深刻度</th><th scope="col">対象</th><th scope="col">種別</th><th scope="col">検知</th><th scope="col">解決</th></tr>
            </thead>
            <tbody>
              {xs.map((x) => (
                <tr key={x.id}>
                  <th scope="row">{link("incidents", x.id)}</th>
                  <td><IncStatus s={x.status} /></td><td><Sev s={x.severity} /></td>
                  <td>{x.subject}</td><td>{x.kind}</td>
                  <td><Time at={x.detected_at} /></td>
                  <td>{x.resolved_at ? <Time at={x.resolved_at} /> : <span className="dim">-</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Async>
    </>
  );
}

function IncidentView({ id }: { id: string }) {
  const r = useGet<IncidentDetail>(`/incidents/${encodeURIComponent(id)}`);
  return (
    <>
      <Back to="incidents" label="Incident 一覧" />
      <Async r={r}>
        {(x) => (
          <>
            <h2>{x.id} <span className="dim">{x.kind}</span></h2>
            <p><IncStatus s={x.status} /> <Sev s={x.severity} /></p>
            <dl className="kv">
              <div><dt>対象</dt><dd>{x.subject}</dd></div>
              <div><dt>検知</dt><dd><Time at={x.detected_at} /></dd></div>
              <div><dt>確認</dt><dd>{x.acknowledged_at ? <Time at={x.acknowledged_at} /> : "-"}</dd></div>
              <div><dt>解決</dt><dd>{x.resolved_at ? <><Time at={x.resolved_at} /> ({x.resolved_by})</> : "-"}</dd></div>
            </dl>
            <h3>影響を受ける Service</h3>
            {x.affected_services.length
              ? <ul className="plain">{x.affected_services.map((s) => <li key={s}>{link("services", s)}</li>)}</ul>
              : <p className="dim">なし</p>}
            <h3>診断</h3>
            {x.diagnosis
              ? <pre className="wrap">{x.diagnosis}</pre>
              : <p>診断未実施{x.diagnosis_status && x.diagnosis_status !== "none" && <span className="dim"> ({x.diagnosis_status})</span>}</p>}
            <h3>Event</h3>
            <ol className="plain">
              {x.events.map((e) => (
                <li key={e.id} className="card">
                  <strong>#{e.id}</strong> <span className="badge">{e.role}</span> {e.subject} {e.kind}: {e.from} → {e.to}{" "}
                  <Time at={e.detected_at} label="検知: " />
                  <EvidenceList ev={e.evidence} />
                </li>
              ))}
            </ol>
          </>
        )}
      </Async>
    </>
  );
}

function Nodes() {
  const r = useGet<NodeInfo[]>("/nodes");
  return (
    <Async r={r}>
      {(ns) => ns.length === 0 ? <p>Node は登録されていません。</p> : (
        <table>
          <thead>
            <tr><th scope="col">Host</th><th scope="col">接続</th><th scope="col">最終受信</th><th scope="col">OS</th><th scope="col">バージョン</th><th scope="col">ホスト名</th></tr>
          </thead>
          <tbody>
            {ns.map((n) => (
              <tr key={n.host_id}>
                <th scope="row">{link("hosts", n.host_id)}</th>
                <td>
                  {n.connected
                    ? <span className="badge s-healthy"><span aria-hidden="true">● </span>接続中</span>
                    : <span className="badge s-unhealthy"><span aria-hidden="true">○ </span>切断</span>}
                </td>
                <td><Time at={n.last_seen} /></td>
                <td>{n.os ?? ""}</td><td>{n.version ?? ""}</td><td>{n.hostname ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Async>
  );
}

// ---- 枠 ----

function Login({ onLogin }: { onLogin: () => void }) {
  const [v, setV] = useState("");
  const [err, setErr] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setToken(v.trim());
    try {
      await get("/summary");
      onLogin();
    } catch (x) {
      clearToken();
      setErr(x instanceof Unauthorized ? "トークンが無効です。" : `接続できませんでした: ${(x as Error).message}`);
    }
  };
  return (
    <main className="login">
      <h1>Ancilla</h1>
      <form onSubmit={submit}>
        <label htmlFor="tok">API トークン（read 以上）</label>
        <input id="tok" type="password" autoComplete="off" value={v} onChange={(e) => setV(e.target.value)} required />
        <button type="submit">ログイン</button>
        {err && <p role="alert" className="err">{err}</p>}
        <p className="dim">発行: <code>ancilla api token create webui --role read</code></p>
      </form>
    </main>
  );
}

const NAV: [string, string][] = [["", "概要"], ["hosts", "Host"], ["services", "Service"], ["incidents", "Incident"], ["nodes", "Node"]];
const CONN: Record<Conn, string> = {
  connecting: "リアルタイム更新: 接続中…", open: "リアルタイム更新: 接続済み", retrying: "リアルタイム更新: 再接続中…",
};

function useHash() {
  const [h, setH] = useState(location.hash);
  useEffect(() => {
    const f = () => setH(location.hash);
    addEventListener("hashchange", f);
    return () => removeEventListener("hashchange", f);
  }, []);
  const [kind = "", id] = h.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  return { kind, id };
}

function Shell({ logout }: { logout: () => void }) {
  const [rev, setRev] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [conn, setConn] = useState<Conn>("connecting");
  const { kind, id } = useHash();

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 15000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const ac = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const bump = () => { // 連続イベントは 300ms にまとめて取り直す
      clearTimeout(timer);
      timer = setTimeout(() => { setRev((x) => x + 1); setNow(Date.now()); }, 300);
    };
    void stream(bump, setConn, logout, ac.signal);
    return () => { ac.abort(); clearTimeout(timer); };
  }, [logout]);

  let view: ReactNode;
  if (kind === "hosts") view = id ? <HostDetail id={id} /> : <HostList />;
  else if (kind === "services") view = id ? <ServiceDetail id={id} /> : <ServiceList />;
  else if (kind === "incidents") view = id ? <IncidentView id={id} /> : <IncidentList />;
  else if (kind === "nodes") view = <Nodes />;
  else view = <Overview />;
  const title = NAV.find(([k]) => k === kind)?.[1] ?? "概要";

  return (
    <Ctx.Provider value={{ rev, now, logout }}>
      <header>
        <strong>Ancilla</strong>
        <nav aria-label="メイン">
          {NAV.map(([k, label]) => (
            <a key={k} href={`#/${k}`} aria-current={k === kind ? "page" : undefined}>{label}</a>
          ))}
        </nav>
        <span className={`conn c-${conn}`} role="status">{CONN[conn]}</span>
        <button type="button" onClick={logout}>ログアウト</button>
      </header>
      <main>
        <h1>{title}</h1>
        {view}
      </main>
    </Ctx.Provider>
  );
}

export function App() {
  const [authed, setAuthed] = useState(!!getToken());
  const logoutRef = useRef(() => { clearToken(); setAuthed(false); });
  return authed ? <Shell logout={logoutRef.current} /> : <Login onLogin={() => setAuthed(true)} />;
}
