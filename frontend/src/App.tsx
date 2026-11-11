import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import "./App.css";
import { checkAccessKey, clearAccessKey, getAccessKey, getAccessStatus, setAccessKey } from "./access";
import AccessGate from "./AccessGate";
import { ApiError, postAsk } from "./api";
import ChatMode from "./ChatMode";
import TableMode from "./TableMode";
import ExportMenu from "./ExportMenu";
import SettingsPanel from "./SettingsPanel";
import { OverflowSql, ResultTableView } from "./Overflow";
import type { AskResponse, HistoryTurn } from "./types";
import { useComposerBox } from "./useComposerBox";

const TIMING_STEPS: { key: keyof AskResponse["timing"]; label: string }[] = [
  { key: "prune_ms", label: "剪枝" },
  { key: "generate_ms", label: "生成" },
  { key: "l1_ms", label: "L1" },
  { key: "l2_ms", label: "L2" },
  { key: "execute_ms", label: "执行" },
  { key: "probe_ms", label: "探针" },
  { key: "total_ms", label: "合计" },
];

export default function App() {
  const [uiMode, setUiMode] = useState<"lab" | "chat" | "tables">("lab");
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AskResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [statusHint, setStatusHint] = useState("");
  const [history, setHistory] = useState<HistoryTurn[]>([]);
  const [chatEpoch, setChatEpoch] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [gate, setGate] = useState<"checking" | "locked" | "open">("checking");
  const [accessRequired, setAccessRequired] = useState(false);
  const { boxRef, taRef, resetSize } = useComposerBox(question);

  const clarifying = result?.stage === "clarify" || history.some((t) => t.role === "assistant");
  const hasProbe =
    Boolean(result?.probe_message) ||
    Boolean(result?.probe_suggestions?.length) ||
    Boolean(result?.degraded && result?.message && result.stage !== "clarify");

  const chipTables = useMemo(() => {
    if (!result) return [];
    const { tables, seed_tables, bridge_tables } = result.prune_summary;
    return [
      ...seed_tables.map((t) => ({ t, kind: "seed" as const })),
      ...bridge_tables.map((t) => ({ t, kind: "bridge" as const })),
      ...tables
        .filter((t) => !seed_tables.includes(t) && !bridge_tables.includes(t))
        .map((t) => ({ t, kind: "other" as const })),
    ];
  }, [result]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const status = await getAccessStatus();
        if (cancelled) return;
        if (!status.required) {
          setGate("open");
          return;
        }
        setAccessRequired(true);
        const saved = getAccessKey();
        if (saved && (await checkAccessKey())) {
          if (!cancelled) setGate("open");
          return;
        }
        clearAccessKey();
        if (!cancelled) setGate("locked");
      } catch {
        if (!cancelled) setGate("locked");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function unlock(key: string): Promise<string> {
    setAccessKey(key);
    try {
      const ok = await checkAccessKey();
      if (!ok) {
        clearAccessKey();
        return "密钥不正确";
      }
    } catch {
      clearAccessKey();
      return "无法连接服务";
    }
    setAccessRequired(true);
    setGate("open");
    return "";
  }

  async function onAsk() {
    const q = question.trim();
    if (!q || loading) return;
    setLoading(true);
    setError("");
    setStatusHint("");
    try {
      const data = await postAsk(q, history);
      setResult(data);
      if (data.stage === "clarify" && data.message) {
        const prior = history.length ? [...history] : [];
        const last = prior[prior.length - 1];
        if (!last || last.role !== "user" || last.content !== q) {
          prior.push({ role: "user", content: q });
        }
        prior.push({ role: "assistant", content: data.message });
        setHistory(prior);
        setQuestion("");
        resetSize();
      } else {
        setHistory([]);
      }
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof TypeError
            ? "无法连接 API。请先运行：querypilot serve --host 127.0.0.1 --port 8000"
            : err instanceof Error
              ? err.message
              : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void onAsk();
    }
  }

  if (gate === "checking") {
    return (
      <div className="gate">
        <p className="muted">正在确认…</p>
      </div>
    );
  }
  if (gate === "locked") {
    return <AccessGate onSubmit={unlock} />;
  }

  return (
    <div className={uiMode === "chat" ? "app app-chat" : "app"}>
      <header className="header">
        <div className="header-row">
          <h1>QueryPilot</h1>
          <div className="header-actions">
            {accessRequired ? (
              <button type="button" className="header-ghost header-logout" onClick={() => { clearAccessKey(); setGate("locked"); }}>
                退出
              </button>
            ) : null}
            <button
              type="button"
              className="header-ghost"
              aria-haspopup="dialog"
              aria-expanded={settingsOpen}
              onClick={() => setSettingsOpen(true)}
            >
              设置
            </button>
            {uiMode === "chat" ? (
              <button
                type="button"
                className="header-ghost"
                onClick={() => setChatEpoch((n) => n + 1)}
              >
                新对话
              </button>
            ) : null}
            <div className="mode-toggle" role="tablist" aria-label="界面模式">
              <button
                type="button"
                role="tab"
                aria-selected={uiMode === "lab"}
                className={uiMode === "lab" ? "active" : ""}
                onClick={() => setUiMode("lab")}
              >
                问数
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={uiMode === "chat"}
                className={uiMode === "chat" ? "active" : ""}
                onClick={() => setUiMode("chat")}
              >
                对话
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={uiMode === "tables"}
                className={uiMode === "tables" ? "active" : ""}
                onClick={() => setUiMode("tables")}
              >
                表格
              </button>
            </div>
          </div>
        </div>
      </header>

      <div hidden={uiMode !== "lab"} className="lab-host">
        <p className="lab-lead">用自然语言提问，生成只读 SQL 并返回结果表。</p>
        <div className="composer" ref={boxRef}>
          <textarea
            ref={taRef}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={clarifying ? "针对追问补充说明…" : "输入问题，Enter 发送"}
            rows={1}
            aria-label="问句"
            disabled={loading}
          />
          <div className="composer-bar">
            <button type="button" onClick={onAsk} disabled={loading || !question.trim()}>
              {loading ? "询问中…" : clarifying ? "追加说明" : "发送"}
            </button>
          </div>
        </div>
        {loading ? <p className="muted lab-status">正在查询…</p> : null}
        {error ? <div className="alert lab-status">{error}</div> : null}
        {statusHint ? <p className="muted lab-status">{statusHint}</p> : null}

        {result ? (
          <>
            {result.stage === "clarify" || history.length > 0 ? (
              <section className="panel">
                <h2>需要补充</h2>
                {history.map((turn, i) => (
                  <p
                    key={`${turn.role}-${i}`}
                    className={turn.role === "assistant" ? "clarify" : "muted"}
                  >
                    <strong>{turn.role === "assistant" ? "助手" : "你"}：</strong>
                    {turn.content}
                  </p>
                ))}
                {result.stage === "clarify" &&
                result.message &&
                history.every((t) => t.content !== result.message) ? (
                  <p className="clarify">
                    <strong>助手：</strong>
                    {result.message}
                  </p>
                ) : null}
              </section>
            ) : null}

            <section className="panel">
              <h2 className="panel-head">
                <span>结果 · {result.row_count} 行</span>
                <ExportMenu
                  columns={result.columns}
                  rows={result.rows}
                  question={result.question}
                  sql={result.sql}
                  onHint={(text) => {
                    setError("");
                    setStatusHint(text);
                  }}
                  onError={(text) => {
                    setStatusHint("");
                    setError(text);
                  }}
                />
              </h2>
              {result.columns.length === 0 ? (
                <p className="muted">{result.stage === "clarify" ? "补充后即可出表。" : "无结果列"}</p>
              ) : (
                <ResultTableView columns={result.columns} rows={result.rows} />
              )}
            </section>

            <section className="panel">
              <h2>SQL</h2>
              {result.sql ? (
                <OverflowSql sql={result.sql} />
              ) : (
                <p className="muted">
                  {result.stage === "clarify" ? "等待补充后生成 SQL。" : "无 SQL"}
                </p>
              )}
            </section>

            <details className="panel process">
              <summary>
                过程与耗时
                <span className="process-meta">
                  {result.timing.total_ms.toFixed(0)} ms
                  {result.timing.cache_hit ? " · 缓存" : ""}
                  {chipTables.length ? ` · ${chipTables.length} 张表` : ""}
                </span>
              </summary>
              <div className="process-body">
                <div className="timeline">
                  {TIMING_STEPS.map(({ key, label }) => (
                    <div className="timeline-item" key={key}>
                      <span className="label">{label}</span>
                      <span className="value">{Number(result.timing[key]).toFixed(1)} ms</span>
                    </div>
                  ))}
                </div>
                {chipTables.length > 0 ? (
                  <div className="chips">
                    {chipTables.map(({ t, kind }) => (
                      <span className="chip" key={`${kind}-${t}`}>
                        {kind === "bridge" ? "桥接 " : kind === "seed" ? "种子 " : ""}
                        {t}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="muted">无表命中</p>
                )}
                {result.prune_summary.metrics.length > 0 ? (
                  <p className="muted">指标：{result.prune_summary.metrics.join(", ")}</p>
                ) : null}
              </div>
            </details>

            {hasProbe ? (
              <section className="panel">
                <h2>提示</h2>
                <div className="alert">
                  {result.message ? <div>{result.message}</div> : null}
                  {result.probe_message ? <div>{result.probe_message}</div> : null}
                  {result.probe_suggestions?.length ? (
                    <ul>
                      {result.probe_suggestions.map((s) => (
                        <li key={s}>{s}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              </section>
            ) : null}
          </>
        ) : null}
      </div>

      <div hidden={uiMode !== "tables"} className="catalog-page">
        <TableMode />
      </div>

      <div hidden={uiMode !== "chat"} className="chat-host">
        <ChatMode resetEpoch={chatEpoch} />
      </div>
      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
