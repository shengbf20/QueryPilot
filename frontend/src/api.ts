import type { AskResponse } from "./types";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function readErrorMessage(resp: Response): Promise<string> {
  const text = await resp.text();
  try {
    const data = JSON.parse(text) as { detail?: unknown };
    if (typeof data.detail === "string") return data.detail;
    if (data.detail != null) return JSON.stringify(data.detail);
  } catch {
    /* use raw text */
  }
  return text || `HTTP ${resp.status}`;
}

export async function postAsk(question: string): Promise<AskResponse> {
  const resp = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify({ question }),
  });
  if (!resp.ok) {
    throw new ApiError(await readErrorMessage(resp), resp.status);
  }
  return (await resp.json()) as AskResponse;
}

export async function exportCsv(
  columns: string[],
  rows: unknown[][],
  filename = "querypilot_export.csv",
): Promise<void> {
  const resp = await fetch("/api/export", {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify({ columns, rows, filename }),
  });
  if (!resp.ok) {
    throw new ApiError(await readErrorMessage(resp), resp.status);
  }
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.endsWith(".csv") ? filename : `${filename}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
