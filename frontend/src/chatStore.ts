import type { ChatMessage, ChatThread } from "./types";

const KEY = "querypilot.chats.v1";
const MAX_THREADS = 40;

export type ChatStore = {
  activeId: string;
  threads: ChatThread[];
};

export function newChatId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function titleFromMessages(messages: ChatMessage[]): string {
  const first = messages.find((m) => m.role === "user")?.text.trim() ?? "";
  const oneLine = first.replace(/\s+/g, " ");
  if (!oneLine) return "新对话";
  return oneLine.length > 28 ? `${oneLine.slice(0, 28)}…` : oneLine;
}

export function loadStore(): ChatStore {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { activeId: "", threads: [] };
    const data = JSON.parse(raw) as ChatStore;
    if (!Array.isArray(data.threads)) return { activeId: "", threads: [] };
    const threads = data.threads.filter(
      (t) => t && typeof t.id === "string" && Array.isArray(t.messages) && t.messages.length > 0,
    );
    const activeId = typeof data.activeId === "string" ? data.activeId : "";
    return { activeId, threads };
  } catch {
    return { activeId: "", threads: [] };
  }
}

export function saveStore(store: ChatStore): void {
  const threads = store.threads
    .filter((t) => t.messages.length > 0)
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, MAX_THREADS);
  const payload: ChatStore = { activeId: store.activeId, threads };
  try {
    localStorage.setItem(KEY, JSON.stringify(payload));
    return;
  } catch {
    /* quota: drop rows from older threads, then drop oldest */
  }
  const slim: ChatStore = {
    activeId: payload.activeId,
    threads: payload.threads.map((t, i) => (i < 3 ? t : slimThread(t))),
  };
  try {
    localStorage.setItem(KEY, JSON.stringify(slim));
  } catch {
    localStorage.setItem(
      KEY,
      JSON.stringify({
        activeId: payload.activeId,
        threads: payload.threads.slice(0, 6).map(slimThread),
      }),
    );
  }
}

export function upsertThread(threads: ChatThread[], next: ChatThread): ChatThread[] {
  return [next, ...threads.filter((t) => t.id !== next.id)].sort((a, b) => b.updatedAt - a.updatedAt);
}

export function groupThreads(threads: ChatThread[]): { label: string; threads: ChatThread[] }[] {
  const today: ChatThread[] = [];
  const yesterday: ChatThread[] = [];
  const older: ChatThread[] = [];
  const startToday = new Date();
  startToday.setHours(0, 0, 0, 0);
  const t0 = startToday.getTime();
  const t1 = t0 - 86_400_000;
  for (const t of threads) {
    if (t.updatedAt >= t0) today.push(t);
    else if (t.updatedAt >= t1) yesterday.push(t);
    else older.push(t);
  }
  return [
    { label: "今天", threads: today },
    { label: "昨天", threads: yesterday },
    { label: "更早", threads: older },
  ].filter((g) => g.threads.length > 0);
}

function slimThread(thread: ChatThread): ChatThread {
  return {
    ...thread,
    messages: thread.messages.map((m) => {
      if (!m.result?.rows?.length) return m;
      return { ...m, result: { ...m.result, rows: m.result.rows.slice(0, 50) } };
    }),
  };
}
