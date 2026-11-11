import { useState, type FormEvent } from "react";

type AccessGateProps = {
  onSubmit: (key: string) => Promise<string>;
};

export default function AccessGate({ onSubmit }: AccessGateProps) {
  const [key, setKey] = useState("");
  const [visible, setVisible] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const value = key.trim();
    if (!value || busy) return;
    setBusy(true);
    setError("");
    try {
      setError(await onSubmit(value));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="gate">
      <form className="gate-card" onSubmit={(e) => void submit(e)}>
        <h1>QueryPilot</h1>
        <p className="gate-lead">输入访问密钥后即可使用。</p>
        <div className="gate-label-row">
          <label htmlFor="access-key">访问密钥</label>
          <button type="button" className="gate-toggle" onClick={() => setVisible((v) => !v)}>
            {visible ? "隐藏" : "显示"}
          </button>
        </div>
        <input
          id="access-key"
          value={key}
          autoFocus
          autoComplete="current-password"
          type={visible ? "text" : "password"}
          placeholder="请输入访问密钥"
          onChange={(e) => setKey(e.target.value)}
        />
        {error ? <p className="gate-error">{error}</p> : null}
        <button className="gate-submit" type="submit" disabled={busy || !key.trim()}>
          {busy ? "正在确认…" : "进入"}
        </button>
      </form>
    </div>
  );
}
