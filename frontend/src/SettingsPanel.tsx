import { useEffect, useId, useState } from "react";
import { ApiError, getSettings, putSettings } from "./api";

type Props = {
  open: boolean;
  onClose: () => void;
};

export default function SettingsPanel({ open, onClose }: Props) {
  const titleId = useId();
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [masked, setMasked] = useState("");
  const [keySet, setKeySet] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [hint, setHint] = useState("");

  useEffect(() => {
    if (!open) return;
    setError("");
    setHint("");
    setApiKey("");
    setLoading(true);
    void getSettings()
      .then((data) => {
        setBaseUrl(data.base_url);
        setModel(data.model);
        setMasked(data.api_key_masked);
        setKeySet(data.api_key_set);
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : "无法读取设置。");
      })
      .finally(() => setLoading(false));
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKey(ev: KeyboardEvent) {
      if (ev.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  async function onSave() {
    if (saving) return;
    setSaving(true);
    setError("");
    setHint("");
    try {
      const body: { api_key?: string; base_url?: string; model?: string } = {
        base_url: baseUrl.trim(),
        model: model.trim(),
      };
      if (apiKey.trim()) body.api_key = apiKey.trim();
      const data = await putSettings(body);
      setMasked(data.api_key_masked);
      setKeySet(data.api_key_set);
      setApiKey("");
      setHint("已保存，后续问数与对话将使用新配置。");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "保存失败。");
    } finally {
      setSaving(false);
    }
  }

  if (!open) return null;

  return (
    <div className="settings-backdrop" onClick={onClose}>
      <div
        className="settings-dialog panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id={titleId}>API 设置</h2>
        <p className="muted settings-lead">
          配置兼容 OpenAI 的接口。密钥只保存在本机，界面只显示掩码。
        </p>
        {loading ? <p className="muted">读取中…</p> : null}
        <label className="settings-field">
          <span>接口地址</span>
          <input
            type="text"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://api.deepseek.com"
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
            disabled={loading || saving}
          />
        </label>
        <label className="settings-field">
          <span>模型名</span>
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="模型 ID"
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
            disabled={loading || saving}
          />
        </label>
        <label className="settings-field">
          <span>API Key</span>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={keySet ? `已配置 ${masked}，留空则不改` : "尚未配置"}
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
            disabled={loading || saving}
          />
        </label>
        {error ? <div className="alert">{error}</div> : null}
        {hint ? <p className="muted">{hint}</p> : null}
        <div className="settings-actions">
          <button type="button" className="action-btn" onClick={onClose}>
            关闭
          </button>
          <button type="button" className="settings-save" onClick={() => void onSave()} disabled={loading || saving}>
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}
