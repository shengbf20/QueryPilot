import { useEffect, useState } from "react";
import { ApiError, getCatalog, getCatalogTable, type CatalogDetail, type CatalogTable } from "./api";
import { ResultTableView } from "./Overflow";

const PAGE = 50;

function rangeLabel(detail: CatalogDetail): string {
  if (detail.row_count === 0) return "没有数据";
  const start = detail.offset + 1;
  const end = Math.min(detail.offset + detail.rows.length, detail.row_count);
  return `第 ${start}–${end} 行，共 ${detail.row_count} 行`;
}

export default function TableMode() {
  const [tables, setTables] = useState<CatalogTable[] | null>(null);
  const [listError, setListError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<CatalogDetail | null>(null);
  const [detailError, setDetailError] = useState("");
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [notesOpen, setNotesOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getCatalog()
      .then((items) => {
        if (!cancelled) setTables(items);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setListError(err instanceof ApiError ? err.message : "无法读取表清单");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function openTable(name: string, offset: number) {
    if (selected !== name) setNotesOpen(false);
    setSelected(name);
    setLoadingDetail(true);
    setDetailError("");
    try {
      const data = await getCatalogTable(name, offset, PAGE);
      setDetail(data);
    } catch (err) {
      setDetail(null);
      setDetailError(err instanceof ApiError ? err.message : "无法读取这张表");
    } finally {
      setLoadingDetail(false);
    }
  }

  if (selected) {
    const title = detail?.alias || selected;
    return (
      <div className="catalog-host">
        <div className="catalog-toolbar">
          <button type="button" className="catalog-back" onClick={() => setSelected(null)}>
            返回列表
          </button>
        </div>
        <section className="panel catalog-detail">
          <h2>{title}</h2>
          {detail ? (
            <>
              <p className="catalog-meta">
                {detail.layer}
                {detail.primary_key.length ? ` · 主键 ${detail.primary_key.join("、")}` : ""}
                {` · ${detail.row_count} 行`}
              </p>
              {detail.description ? <p>{detail.description}</p> : null}
              {detail.grain || detail.notes.length ? (
                <p className="catalog-note-line">
                  <button type="button" className="catalog-back" onClick={() => setNotesOpen((v) => !v)}>
                    {notesOpen ? "收起说明" : "说明"}
                  </button>
                </p>
              ) : null}
              {notesOpen ? (
                <div className="catalog-notes">
                  {detail.grain ? <p>一行表示：{detail.grain}</p> : null}
                  {detail.notes.map((note) => (
                    <p key={note}>{note}</p>
                  ))}
                </div>
              ) : null}
              <h3>列</h3>
              <dl className="catalog-cols">
                {detail.columns.map((col) => (
                  <div key={col.name}>
                    <dt>{col.name}</dt>
                    <dd>{col.description || "—"}</dd>
                  </div>
                ))}
              </dl>
              <div className="catalog-toolbar">
                <h3>数据</h3>
                <span className="muted">{loadingDetail ? "正在读取…" : rangeLabel(detail)}</span>
              </div>
              {detail.rows.length ? (
                <ResultTableView columns={detail.data_columns} rows={detail.rows} />
              ) : (
                <p className="muted">这张表没有数据。</p>
              )}
              <div className="catalog-pager">
                <button
                  type="button"
                  className="ghost"
                  disabled={loadingDetail || detail.offset <= 0}
                  onClick={() => void openTable(selected, Math.max(0, detail.offset - PAGE))}
                >
                  上一页
                </button>
                <button
                  type="button"
                  className="ghost"
                  disabled={loadingDetail || detail.offset + detail.rows.length >= detail.row_count}
                  onClick={() => void openTable(selected, detail.offset + PAGE)}
                >
                  下一页
                </button>
              </div>
            </>
          ) : (
            <p className="muted">{detailError || "正在读取…"}</p>
          )}
        </section>
      </div>
    );
  }

  return (
    <div className="catalog-host">
      <div className="catalog-toolbar">
        <p className="catalog-lead">已登记的表。点开可看含义和数据。</p>
        <a className="catalog-add" href="/onboarding">
          新增表格
        </a>
      </div>
      {listError ? <div className="alert">{listError}</div> : null}
      {tables === null && !listError ? <p className="muted">正在读取…</p> : null}
      {tables && tables.length === 0 ? <p className="muted">还没有登记任何表。</p> : null}
      <ul className="catalog-list">
        {(tables ?? []).map((table) => (
          <li key={table.name}>
            <button type="button" className="catalog-item" onClick={() => void openTable(table.name, 0)}>
              <span className="catalog-item-title">
                <strong>{table.alias}</strong>
                <span className="pill hit">{table.layer}</span>
              </span>
              <span className="muted catalog-item-name">{table.name}</span>
              {table.description ? <span className="catalog-item-desc">{table.description}</span> : null}
              <span className="muted">
                {table.column_count} 列 · {table.row_count} 行
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
