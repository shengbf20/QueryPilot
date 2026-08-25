import { groupThreads } from "./chatStore";
import type { ChatThread } from "./types";

type Props = {
  open: boolean;
  threads: ChatThread[];
  activeId: string;
  onToggle: () => void;
  onNew: () => void;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
};

export default function ChatSidebar({
  open,
  threads,
  activeId,
  onToggle,
  onNew,
  onOpen,
  onDelete,
}: Props) {
  const groups = groupThreads(threads);

  if (!open) {
    return (
      <aside className="chat-sidebar is-collapsed" aria-label="历史对话">
        <button type="button" className="chat-rail-btn" onClick={onToggle} aria-label="展开历史">
          ›
        </button>
        <button type="button" className="chat-rail-btn" onClick={onNew} aria-label="新对话">
          +
        </button>
      </aside>
    );
  }

  return (
    <aside className="chat-sidebar" aria-label="历史对话">
      <div className="chat-sidebar-head">
        <button type="button" className="chat-new" onClick={onNew}>
          新对话
        </button>
        <button type="button" className="chat-rail-btn" onClick={onToggle} aria-label="收起历史">
          ‹
        </button>
      </div>
      <div className="chat-hist">
        {groups.length === 0 ? (
          <p className="chat-hist-empty">还没有历史对话</p>
        ) : (
          groups.map((group) => (
            <section key={group.label}>
              <h3 className="chat-hist-label">{group.label}</h3>
              <ul className="chat-hist-list">
                {group.threads.map((t) => (
                  <li key={t.id}>
                    <div className={t.id === activeId ? "chat-hist-item active" : "chat-hist-item"}>
                      <button
                        type="button"
                        className="chat-hist-open"
                        onClick={() => onOpen(t.id)}
                        title={t.title}
                      >
                        {t.title}
                      </button>
                      <button
                        type="button"
                        className="chat-hist-del"
                        aria-label={`删除「${t.title}」`}
                        onClick={() => onDelete(t.id)}
                      >
                        ×
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ))
        )}
      </div>
    </aside>
  );
}
