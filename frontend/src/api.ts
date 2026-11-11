import { accessHeaders } from "./access";
import type { AskResponse, HistoryTurn } from "./types";

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

export async function postAsk(
  question: string,
  history: HistoryTurn[] = [],
  opts: { mode?: "fast" | "agent"; sessionId?: string } = {},
): Promise<AskResponse> {
  const resp = await fetch("/api/ask", {
    method: "POST",
    headers: accessHeaders({ "Content-Type": "application/json; charset=utf-8" }),
    body: JSON.stringify({
      question,
      history,
      mode: opts.mode ?? "fast",
      session_id: opts.sessionId ?? "",
      max_rows: 100000,
    }),
  });
  if (!resp.ok) {
    throw new ApiError(await readErrorMessage(resp), resp.status);
  }
  return (await resp.json()) as AskResponse;
}

export type LlmSettings = {
  api_key_set: boolean;
  api_key_masked: string;
  base_url: string;
  model: string;
};

export async function getSettings(): Promise<LlmSettings> {
  const resp = await fetch("/api/settings", { headers: accessHeaders() });
  if (!resp.ok) {
    throw new ApiError(await readErrorMessage(resp), resp.status);
  }
  return (await resp.json()) as LlmSettings;
}

export type CatalogTable = {
  name: string;
  alias: string;
  layer: string;
  description: string;
  column_count: number;
  row_count: number;
};

export type CatalogDetail = CatalogTable & {
  primary_key: string[];
  grain: string;
  notes: string[];
  columns: { name: string; description: string }[];
  offset: number;
  limit: number;
  data_columns: string[];
  rows: unknown[][];
};

export async function getCatalog(): Promise<CatalogTable[]> {
  const resp = await fetch("/api/catalog/tables", { headers: accessHeaders() });
  if (!resp.ok) {
    throw new ApiError(await readErrorMessage(resp), resp.status);
  }
  const data = (await resp.json()) as { tables: CatalogTable[] };
  return data.tables;
}

export async function getCatalogTable(name: string, offset: number, limit = 50): Promise<CatalogDetail> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  const resp = await fetch(`/api/catalog/tables/${encodeURIComponent(name)}?${params}`, {
    headers: accessHeaders(),
  });
  if (!resp.ok) {
    throw new ApiError(await readErrorMessage(resp), resp.status);
  }
  return (await resp.json()) as CatalogDetail;
}

export async function putSettings(body: {
  api_key?: string;
  base_url?: string;
  model?: string;
}): Promise<LlmSettings> {
  const resp = await fetch("/api/settings", {
    method: "PUT",
    headers: accessHeaders({ "Content-Type": "application/json; charset=utf-8" }),
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    throw new ApiError(await readErrorMessage(resp), resp.status);
  }
  return (await resp.json()) as LlmSettings;
}

