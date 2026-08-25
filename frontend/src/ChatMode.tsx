import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ApiError, postAsk } from "./api";
import ChatSidebar from "./ChatSidebar";
import { loadStore, newChatId, saveStore, titleFromMessages, upsertThread } from "./chatStore";
import ExportMenu from "./ExportMenu";
import { OverflowSql, ResultTableView } from "./Overflow";
import { summarizeAsk } from "./summarize";
import { useComposerBox } from "./useComposerBox";
import type { AskResponse, ChatMessage, ChatThread, HistoryTurn } from "./types";

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
  return newChatId();
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
      <span className="block-kicker">结果表</span>
      <div className="chat-table">
        <ResultTableView columns={result.columns} rows={result.rows} />
      </div>
    </div>
  );
}

function collectThoughts(result?: AskResponse): string {
  if (!result) return "";
  const parts: string[] = [];
  const rationale = result.rationale?.trim();
  if (rationale) parts.push(rationale);
  const trace = result.extras?.agent_trace;
  if (Array.isArray(trace)) {
    for (const step of trace) {
      if (!step || typeof step !== "object") continue;
      const thought = String((step as { thought?: unknown }).thought || "").trim();
      if (thought && !parts.includes(thought)) parts.push(thought);
    }
  }
  return parts.join("\n\n");
}

function AssistantBody({
  msg,
  detailsOpen,
  thoughtsOpen,
  onToggleDetails,
  onToggleThoughts,
  onHint,
  onError,
}: {
  msg: ChatMessage;
  detailsOpen: boolean;
  thoughtsOpen: boolean;
  onToggleDetails: () => void;
  onToggleThoughts: () => void;
  onHint: (text: string) => void;
  onError: (text: string) => void;
}) {
  const r = msg.result;
  const safety = r?.stage === "safety";
  const thoughts = collectThoughts(r);
  return (
    <div className="msg-assistant">
      {thoughts ? (
        <div className="thought-wrap">
          <button type="button" className="thought-toggle" onClick={onToggleThoughts}>
            <span className="thought-chevron" aria-hidden>
              {thoughtsOpen ? "▾" : "▸"}
            </span>
            {thoughtsOpen ? "收起思考过程" : "思考过程"}
          </button>
          {thoughtsOpen ? <div className="thought">{thoughts}</div> : null}
        </div>
      ) : null}
      {msg.text ? <p className={safety ? "nl safety-nl" : "nl"}>{msg.text}</p> : null}
      {r?.sql ? <OverflowSql sql={r.sql} /> : null}
      {r ? <ResultTable result={r} /> : null}
      {r ? (
        <div className="msg-actions">
          <button type="button" className="action-btn" onClick={onToggleDetails}>
            {detailsOpen ? "收起" : "详情"}
          </button>
          <ExportMenu
            columns={r.columns}
            rows={r.rows}
            question={r.question}
            sql={r.sql}
            onHint={onHint}
            onError={onError}
          />
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
  resetEpoch?: number;
};

function clearComposer(
  setDraft: (v: string) => void,
  setError: (v: string) => void,
  setHint: (v: string) => void,
  setOpenDetails: (v: Record<string, boolean>) => void,
  setOpenThoughts: (v: Record<string, boolean>) => void,
) {
  setDraft("");
  setError("");
  setHint("");
  setOpenDetails({});
  setOpenThoughts({});
}

export default function ChatMode({ seedQuestion, seedResult, resetEpoch = 0 }: ChatModeProps) {
  const [initial] = useState(loadStore);
  const restored = initial.threads.find((t) => t.id === initial.activeId) ?? initial.threads[0];
  const [threads, setThreads] = useState<ChatThread[]>(initial.threads);
  const [activeId, setActiveId] = useState(restored?.id ?? newId());
  const [messages, setMessages] = useState<ChatMessage[]>(restored?.messages ?? []);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hint, setHint] = useState("");
  const [openDetails, setOpenDetails] = useState<Record<string, boolean>>({});
  const [openThoughts, setOpenThoughts] = useState<Record<string, boolean>>({});
  const skipSeed = useRef(Boolean(restored?.messages.length));
  const prevEpoch = useRef(resetEpoch);
  const bottomRef = useRef<HTMLDivElement>(null);
  const { boxRef, taRef, resetSize, onGripPointerDown } = useComposerBox(draft);

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

  useEffect(() => {
    if (!messages.length) {
      saveStore({ activeId, threads });
      return;
    }
    setThreads((prev) => {
      const existing = prev.find((t) => t.id === activeId);
      if (existing && existing.messages === messages) return prev;
      const next = upsertThread(prev, {
        id: activeId,
        title: titleFromMessages(messages),
        updatedAt: Date.now(),
        messages,
      });
      saveStore({ activeId, threads: next });
      return next;
    });
  }, [messages, activeId]);

  function resetThread() {
    if (loading) return;
    skipSeed.current = true;
    if (!messages.length) return;
    const id = newId();
    setActiveId(id);
    setMessages([]);
    clearComposer(setDraft, setError, setHint, setOpenDetails, setOpenThoughts);
    resetSize();
    saveStore({ activeId: id, threads });
  }

  function openThread(id: string) {
    if (id === activeId || loading) return;
    const t = threads.find((x) => x.id === id);
    if (!t) return;
    skipSeed.current = true;
    setActiveId(id);
    setMessages(t.messages);
    clearComposer(setDraft, setError, setHint, setOpenDetails, setOpenThoughts);
    resetSize();
    saveStore({ activeId: id, threads });
    if (typeof window !== "undefined" && window.innerWidth <= 800) setSidebarOpen(false);
  }

  function deleteThread(id: string) {
    if (loading && id === activeId) return;
    const next = threads.filter((t) => t.id !== id);
    setThreads(next);
    if (id !== activeId) {
      saveStore({ activeId, threads: next });
      return;
    }
    skipSeed.current = true;
    const fallback = next[0];
    if (fallback) {
      setActiveId(fallback.id);
      setMessages(fallback.messages);
      saveStore({ activeId: fallback.id, threads: next });
    } else {
      const fresh = newId();
      setActiveId(fresh);
      setMessages([]);
      saveStore({ activeId: fresh, threads: next });
    }
    clearComposer(setDraft, setError, setHint, setOpenDetails, setOpenThoughts);
    resetSize();
  }

  useEffect(() => {
    if (prevEpoch.current === resetEpoch) return;
    prevEpoch.current = resetEpoch;
    resetThread();
  }, [resetEpoch]);

  async function send() {
    const q = draft.trim();
    if (!q || loading) return;
    skipSeed.current = true;
    const userMsg: ChatMessage = { id: newId(), role: "user", text: q };
    const next = [...messages, userMsg];
    setMessages(next);
    setDraft("");
    resetSize();
    setLoading(true);
    setError("");
    setHint("");
    try {
      const data = await postAsk(q, toHistory(messages), {
        mode: "agent",
        sessionId: activeId,
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
    <div className="chat-layout">
      <ChatSidebar
        open={sidebarOpen}
        threads={threads}
        activeId={activeId}
        onToggle={() => setSidebarOpen((v) => !v)}
        onNew={resetThread}
        onOpen={openThread}
        onDelete={deleteThread}
      />
      {sidebarOpen ? (
        <button
          type="button"
          className="chat-sidebar-mask"
          aria-label="关闭历史"
          onClick={() => setSidebarOpen(false)}
        />
      ) : null}
      <div className="chat-shell">
      <div className="chat-thread">
        <div className={messages.length === 0 && !loading ? "chat-thread-inner is-empty" : "chat-thread-inner"}>
          {messages.length === 0 && !loading ? (
            <div className="chat-empty">
              <p>有什么想查的？</p>
              <p className="chat-empty-hint">用自然语言提问，我会查库并返回结果</p>
            </div>
          ) : null}
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
                  thoughtsOpen={Boolean(openThoughts[msg.id])}
                  onToggleDetails={() =>
                    setOpenDetails((prev) => ({ ...prev, [msg.id]: !prev[msg.id] }))
                  }
                  onToggleThoughts={() =>
                    setOpenThoughts((prev) => ({ ...prev, [msg.id]: !prev[msg.id] }))
                  }
                  onHint={(text) => {
                    setError("");
                    setHint(text);
                  }}
                  onError={(text) => {
                    setHint("");
                    setError(text);
                  }}
                />
              </div>
            ),
          )}
          {loading ? <p className="muted chat-waiting">正在生成…</p> : null}
          {hint ? <p className="muted chat-waiting">{hint}</p> : null}
          {error ? <div className="alert">{error}</div> : null}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="chat-composer-wrap">
        <div
          className="chat-composer"
          ref={(el) => {
            boxRef.current = el;
          }}
        >
          <button
            type="button"
            className="chat-composer-grip"
            aria-label="向上拖动加高输入框"
            onPointerDown={onGripPointerDown}
          />
          <textarea
            ref={taRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="输入问题，Enter 发送"
            rows={1}
            disabled={loading}
            aria-label="消息"
          />
          <div className="chat-composer-bar">
            <button type="button" onClick={() => void send()} disabled={loading || !draft.trim()}>
              发送
            </button>
          </div>
        </div>
      </div>
      </div>
    </div>
  );
}
