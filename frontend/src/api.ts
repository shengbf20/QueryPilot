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
    headers: { "Content-Type": "application/json; charset=utf-8" },
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

