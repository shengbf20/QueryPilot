import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ApiError, exportCsv, postAsk } from "./api";
import { formatCell, summarizeAsk } from "./summarize";
import type { AskResponse, ChatMessage, HistoryTurn } from "./types";

const TIMING_STEPS: { key: keyof AskResponse["timing"]; label: string }[] = [
  { key: "prune_ms", label: "剪枝" },
  { key: "generate_ms", label: "生成" },
  { key: "l1_ms", label: "L1" },
  { key: "l2_ms", label: "L2" },
  { key: "execute_ms", label: "执行" },
  { key: "probe_ms", label: "探针" },
  { key: "total_ms", label: "合计" },
];

function newId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function toHistory(messages: ChatMessage[]): HistoryTurn[] {
  return messages.map((m) => {
    if (m.role === "user") return { role: "user", content: m.text };
    const sql = m.result?.sql?.trim();
    return { role: "assistant", content: sql ? `${m.text}\n${sql}` : m.text };
  });
}

function ResultTable({ result }: { result: AskResponse }) {
  if (!result.columns.length) return null;
  return (
    <div className="result-block">
      <span className="block-kicker">结果表：</span>
      <div className="table-wrap chat-table">
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
    </div>
  );
}

function AssistantBody({
  msg,
  detailsOpen,
  onToggleDetails,
}: {
  msg: ChatMessage;
  detailsOpen: boolean;
  onToggleDetails: () => void;
}) {
  const r = msg.result;
  const safety = r?.stage === "safety";
  return (
    <div className="msg-assistant">
      {r?.rationale ? (
        <div className="thought">
          <span className="block-kicker">思考</span>
          {r.rationale}
        </div>
      ) : null}
      {msg.text ? <p className={safety ? "nl safety-nl" : "nl"}>{msg.text}</p> : null}
      {r?.sql ? <pre className="sql">{r.sql}</pre> : null}
      {r ? <ResultTable result={r} /> : null}
      {r ? (
        <div className="msg-actions">
          <button type="button" className="linkish" onClick={onToggleDetails}>
            {detailsOpen ? "收起" : "详情"}
          </button>
          {r.columns.length ? (
            <button
              type="button"
              className="linkish"
              onClick={() => {
                void exportCsv(r.columns, r.rows);
              }}
            >
              导出
            </button>
          ) : null}
        </div>
      ) : null}
      {detailsOpen && r ? (
        <div className="chat-details">
          <div className="muted">
            {r.stage}
            {r.extras?.mode === "agent" ? " · agent" : ""}
            {r.timing.cache_hit ? " · 缓存" : ""}
            {r.tables.length ? ` · ${r.tables.join(", ")}` : ""}
            {` · ${r.timing.total_ms.toFixed(0)} ms`}
          </div>
          {Array.isArray(r.extras?.agent_trace) && r.extras.agent_trace.length ? (
            <div className="muted" style={{ marginTop: "0.4rem" }}>
              {(r.extras.agent_trace as { tool?: string }[])
                .map((s) => s.tool)
                .filter(Boolean)
                .join(" → ")}
            </div>
          ) : null}
          <div className="timeline compact">
            {TIMING_STEPS.map(({ key, label }) => (
              <div className="timeline-item" key={key}>
                <span className="label">{label}</span>
                <span className="value">{Number(r.timing[key]).toFixed(0)}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

type ChatModeProps = {
  seedQuestion?: string;
  seedResult?: AskResponse | null;
};

export default function ChatMode({ seedQuestion, seedResult }: ChatModeProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [openDetails, setOpenDetails] = useState<Record<string, boolean>>({});
  const skipSeed = useRef(false);
  const sessionId = useRef(newId());
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (skipSeed.current || messages.length > 0 || !seedResult || !seedQuestion) return;
    skipSeed.current = true;
    setMessages([
      { id: newId(), role: "user", text: seedQuestion },
      { id: newId(), role: "assistant", text: summarizeAsk(seedResult), result: seedResult },
    ]);
  }, [messages.length, seedQuestion, seedResult]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send() {
    const q = draft.trim();
    if (!q || loading) return;
    skipSeed.current = true;
    const userMsg: ChatMessage = { id: newId(), role: "user", text: q };
    const next = [...messages, userMsg];
    setMessages(next);
    setDraft("");
    setLoading(true);
    setError("");
    try {
      const data = await postAsk(q, toHistory(messages), {
        mode: "agent",
        sessionId: sessionId.current,
      });
      setMessages([
        ...next,
        { id: newId(), role: "assistant", text: summarizeAsk(data), result: data },
      ]);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof TypeError
            ? "无法连接 API"
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
      void send();
    }
  }

  return (
    <div className="chat-shell">
      <div className="chat-toolbar">
        <button
          type="button"
          className="secondary"
          onClick={() => {
            skipSeed.current = true;
            sessionId.current = newId();
            setMessages([]);
            setError("");
            setOpenDetails({});
          }}
        >
          新对话
        </button>
      </div>

      <div className="chat-thread">
        <div className="chat-thread-inner">
          {messages.length === 0 && !loading ? <p className="chat-empty">有什么想查的？</p> : null}
          {messages.map((msg) =>
            msg.role === "user" ? (
              <div className="msg user" key={msg.id}>
                <div className="msg-user-bubble">{msg.text}</div>
              </div>
            ) : (
              <div className="msg assistant" key={msg.id}>
                <AssistantBody
                  msg={msg}
                  detailsOpen={Boolean(openDetails[msg.id])}
                  onToggleDetails={() =>
                    setOpenDetails((prev) => ({ ...prev, [msg.id]: !prev[msg.id] }))
                  }
                />
              </div>
            ),
          )}
          {loading ? <p className="muted chat-waiting">正在生成…</p> : null}
          {error ? <div className="alert">{error}</div> : null}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="chat-composer-wrap">
        <div className="chat-composer">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="输入消息"
            rows={1}
            disabled={loading}
            aria-label="消息"
          />
          <button type="button" onClick={() => void send()} disabled={loading || !draft.trim()}>
            发送
          </button>
        </div>
      </div>
    </div>
  );
}
