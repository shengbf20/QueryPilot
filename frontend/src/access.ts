const STORAGE_KEY = "querypilot.accessKey";

export function getAccessKey(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setAccessKey(key: string): void {
  localStorage.setItem(STORAGE_KEY, key.trim());
}

export function clearAccessKey(): void {
  localStorage.removeItem(STORAGE_KEY);
}

export function accessHeaders(base?: HeadersInit): Headers {
  const headers = new Headers(base);
  const key = getAccessKey();
  if (key) headers.set("X-Access-Key", key);
  return headers;
}

export async function getAccessStatus(): Promise<{ required: boolean }> {
  const resp = await fetch("/api/access");
  if (!resp.ok) throw new Error("无法确认访问设置");
  return (await resp.json()) as { required: boolean };
}

export async function checkAccessKey(): Promise<boolean> {
  const resp = await fetch("/api/access", { method: "POST", headers: accessHeaders() });
  if (resp.status === 401) return false;
  if (!resp.ok) throw new Error("无法确认访问密钥");
  return true;
}
