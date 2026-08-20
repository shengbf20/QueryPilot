import type { AskResponse } from "./types";

export function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

export function summarizeAsk(result: AskResponse): string {
  if (result.stage === "clarify" && result.message) return result.message;
  if (result.stage === "safety" && result.message) return result.message;
  if (!result.ok) return result.message || "查询未完成。";
  if (result.columns.length && result.rows.length) return result.probe_message || "";
  if (result.row_count === 0) return result.probe_message || "没有查到数据。";
  return result.probe_message || "";
}
