import { accessHeaders } from "./access";
import { ApiError } from "./api";

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

export function exportBasename(question: string): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}`;
  const q = question
    .trim()
    .replace(/[\\/:*?"<>|]+/g, "")
    .replace(/\s+/g, "")
    .slice(0, 24);
  return `问数_${q || "结果"}_${stamp}`;
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function downloadTable(
  columns: string[],
  rows: unknown[][],
  filename: string,
  format: "csv" | "xlsx",
): Promise<void> {
  const resp = await fetch("/api/export", {
    method: "POST",
    headers: accessHeaders({ "Content-Type": "application/json; charset=utf-8" }),
    body: JSON.stringify({ columns, rows, filename, format }),
  });
  if (!resp.ok) {
    throw new ApiError(await readErrorMessage(resp), resp.status);
  }
  const blob = await resp.blob();
  const ext = format === "xlsx" ? ".xlsx" : ".csv";
  const name = filename.toLowerCase().endsWith(ext) ? filename : `${filename}${ext}`;
  triggerDownload(blob, name);
}

function cellText(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

export async function copyTable(columns: string[], rows: unknown[][]): Promise<void> {
  const lines = [
    columns.join("\t"),
    ...rows.map((row) => columns.map((_, i) => cellText(row[i]).replace(/\t/g, " ")).join("\t")),
  ];
  await navigator.clipboard.writeText(lines.join("\n"));
}

export async function copySql(sql: string): Promise<void> {
  await navigator.clipboard.writeText(sql);
}
