import { useMemo, useState } from "react";
import "./App.css";
import { ApiError, exportCsv, postAsk } from "./api";
import { MOCK_ASK_RESPONSE, MOCK_DEGRADED_RESPONSE } from "./mock";
import type { AskResponse, HistoryTurn } from "./types";

const TIMING_STEPS: { key: keyof AskResponse["timing"]; label: string }[] = [
  { key: "prune_ms", label: "剪枝" },
  { key: "generate_ms", label: "生成" },
  { key: "l1_ms", label: "L1" },
  { key: "l2_ms", label: "L2" },
  { key: "execute_ms", label: "执行" },
  { key: "probe_ms", label: "探针" },
  { key: "total_ms", label: "合计" },
];

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

export default function App() {
  const [question, setQuestion] = useState(MOCK_ASK_RESPONSE.question);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [statusHint, setStatusHint] = useState("");
  const [history, setHistory] = useState<HistoryTurn[]>([]);

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

  async function onAsk() {
    const q = question.trim();
    if (!q) {
      setError("问题不能为空");
      return;
    }
    setLoading(true);
    setError("");
    setStatusHint("");
    const previous = result;
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
        setStatusHint("需求不明确，请根据模型提问追加说明后再发送。");
      } else {
        setHistory([]);
        if (data.timing.cache_hit) {
          const prev =
            previous && previous.question === q
              ? `（上次同题 total_ms=${previous.timing.total_ms.toFixed(1)}）`
              : "";
          setStatusHint(`缓存命中：total_ms=${data.timing.total_ms.toFixed(1)}${prev}`);
        } else {
          setStatusHint(
            `冷路径：total_ms=${data.timing.total_ms.toFixed(1)}。同题再发送一次可演示 cache_hit。`,
          );
        }
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

  function loadMockOk() {
    setError("");
    setResult({
      ...MOCK_ASK_RESPONSE,
      question: question.trim() || MOCK_ASK_RESPONSE.question,
    });
    setStatusHint("已加载本地 mock（未请求后端）。");
  }

  function loadMockDegraded() {
    setError("");
    setResult({
      ...MOCK_DEGRADED_RESPONSE,
      question: question.trim() || MOCK_DEGRADED_RESPONSE.question,
    });
    setStatusHint("已加载本地 mock 拦截样例（未请求后端）。");
  }

  async function onExport() {
    if (!result?.columns?.length) {
      setStatusHint("暂无结果可导出。");
      return;
    }
    setError("");
    try {
      await exportCsv(result.columns, result.rows, "querypilot_export.csv");
      setStatusHint("已触发 CSV 下载。");
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof TypeError
            ? "导出失败：无法连接 API（请先 serve）。"
            : err instanceof Error
              ? err.message
              : String(err);
      setError(msg);
    }
  }

  return (
    <div className="app">
      <header className="header">
        <h1>QueryPilot</h1>
        <p>自然语言问数 · Schema 剪枝与耗时透明化</p>
        <span className="badge">LIVE · /api/ask via Vite proxy</span>
      </header>

      <section className="composer">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={clarifying ? "针对模型提问追加说明…" : "输入自然语言问题…"}
          aria-label="问句"
          disabled={loading}
        />
        <div className="composer-actions">
          <button type="button" onClick={onAsk} disabled={loading}>
            {loading ? "询问中…" : clarifying ? "追加说明" : "发送"}
          </button>
          <button
            type="button"
            className="secondary"
            onClick={onExport}
            disabled={!result || loading}
          >
            导出 CSV
          </button>
          <button
            type="button"
            className="secondary"
            onClick={loadMockOk}
            disabled={loading}
          >
            mock 成功
          </button>
          <button
            type="button"
            className="secondary"
            onClick={loadMockDegraded}
            disabled={loading}
          >
            mock 拦截
          </button>
        </div>
        {loading ? <p className="muted">正在请求后端，冷路径可能需数秒…</p> : null}
        {error ? (
          <div className="alert" style={{ marginTop: "0.5rem" }}>
            {error}
          </div>
        ) : null}
        {statusHint ? <p className="muted">{statusHint}</p> : null}
      </section>

      {!result ? (
        <p className="empty">
          先启动 <code>querypilot serve</code>，再点「发送」。同题连发两次可看 cache_hit
          与耗时下降。无后端时可用 mock 按钮。
        </p>
      ) : (
        <>
          <section className="panel">
            <h2>
              分阶段耗时
              <span className={`pill ${result.timing.cache_hit ? "hit" : "miss"}`}>
                cache_hit={String(result.timing.cache_hit)}
              </span>
            </h2>
            <div className="timeline">
              {TIMING_STEPS.map(({ key, label }) => (
                <div className="timeline-item" key={key}>
                  <span className="label">{label}</span>
                  <span className="value">{Number(result.timing[key]).toFixed(1)} ms</span>
                </div>
              ))}
            </div>
          </section>

          <section className="panel">
            <h2>Schema 剪枝摘要</h2>
            {chipTables.length === 0 ? (
              <p className="muted">无表命中</p>
            ) : (
              <div className="chips">
                {chipTables.map(({ t, kind }) => (
                  <span className="chip" key={`${kind}-${t}`}>
                    {kind === "bridge" ? "桥接 " : kind === "seed" ? "种子 " : ""}
                    {t}
                  </span>
                ))}
              </div>
            )}
            {result.prune_summary.metrics.length > 0 ? (
              <p className="muted" style={{ marginTop: "0.6rem" }}>
                metrics: {result.prune_summary.metrics.join(", ")}
              </p>
            ) : null}
            {result.rationale ? (
              <p className="muted" style={{ marginTop: "0.6rem" }}>
                rationale: {result.rationale}
              </p>
            ) : null}
          </section>

          {result.stage === "clarify" || history.length > 0 ? (
            <section className="panel">
              <h2>模型提问 · 追加说明</h2>
              {history.map((turn, i) => (
                <p key={`${turn.role}-${i}`} className={turn.role === "assistant" ? "clarify" : "muted"}>
                  <strong>{turn.role === "assistant" ? "助手" : "你"}：</strong>
                  {turn.content}
                </p>
              ))}
              {result.stage === "clarify" && result.message && history.every((t) => t.content !== result.message) ? (
                <p className="clarify">
                  <strong>助手：</strong>
                  {result.message}
                </p>
              ) : null}
            </section>
          ) : null}

          <section className="panel">
            <h2>SQL 预览 · stage={result.stage || "-"}</h2>
            <pre className="sql">{result.sql || (result.stage === "clarify" ? "(等待补充后生成 SQL)" : "(无 SQL)")}</pre>
          </section>

          <section className="panel">
            <h2>
              结果表 · {result.row_count} 行 · ok={String(result.ok)}
            </h2>
            {result.columns.length === 0 ? (
              <p className="muted">无结果列</p>
            ) : (
              <div className="table-wrap">
                <table className="result">
                  <thead>
                    <tr>
                      {result.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row, i) => (
                      <tr key={i}>
                        {result.columns.map((_, j) => (
                          <td key={j}>{formatCell(row[j])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {hasProbe ? (
            <section className="panel">
              <h2>降级 / 探针</h2>
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
      )}
    </div>
  );
}
