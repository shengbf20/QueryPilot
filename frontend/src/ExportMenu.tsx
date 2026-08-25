import { useEffect, useRef, useState } from "react";
import { ApiError } from "./api";
import { copySql, copyTable, downloadTable, exportBasename } from "./export";

type Props = {
  columns: string[];
  rows: unknown[][];
  question?: string;
  sql?: string;
  onHint?: (text: string) => void;
  onError?: (text: string) => void;
};

export default function ExportMenu({ columns, rows, question = "", sql = "", onHint, onError }: Props) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDoc(ev: MouseEvent) {
      if (!wrapRef.current?.contains(ev.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  function fail(err: unknown): void {
    const msg =
      err instanceof ApiError
        ? err.message
        : err instanceof TypeError
          ? "无法连接 API。"
          : err instanceof Error
            ? err.message
            : String(err);
    onError?.(msg);
  }

  async function onDownload(format: "xlsx" | "csv") {
    setOpen(false);
    try {
      await downloadTable(columns, rows, exportBasename(question), format);
      onHint?.(format === "xlsx" ? "已下载 Excel。" : "已下载 CSV。");
    } catch (err) {
      fail(err);
    }
  }

  async function onCopyTable() {
    setOpen(false);
    try {
      await copyTable(columns, rows);
      onHint?.(`已复制 ${rows.length} 行表格。`);
    } catch (err) {
      fail(err);
    }
  }

  async function onCopySql() {
    setOpen(false);
    try {
      await copySql(sql);
      onHint?.("已复制 SQL。");
    } catch (err) {
      fail(err);
    }
  }

  if (!columns.length) return null;

  return (
    <div className="export-menu" ref={wrapRef}>
      <button type="button" className="action-btn" onClick={() => setOpen((v) => !v)}>
        导出 ▾
      </button>
      {open ? (
        <div className="export-pop" role="menu">
          <button type="button" role="menuitem" onClick={() => void onDownload("xlsx")}>
            下载 Excel
          </button>
          <button type="button" role="menuitem" onClick={() => void onDownload("csv")}>
            下载 CSV
          </button>
          <button type="button" role="menuitem" onClick={() => void onCopyTable()}>
            复制表格
          </button>
          {sql.trim() ? (
            <button type="button" role="menuitem" onClick={() => void onCopySql()}>
              复制 SQL
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
