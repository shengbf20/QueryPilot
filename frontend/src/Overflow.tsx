import { useState } from "react";
import { formatCell } from "./summarize";

const SQL_MAX_LINES = 16;
const TABLE_MAX_ROWS = 12;

export function OverflowSql({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false);
  const lines = sql.split("\n");
  const long = lines.length > SQL_MAX_LINES;
  const text = !long || open ? sql : `${lines.slice(0, SQL_MAX_LINES).join("\n")}\n…`;
  return (
    <>
      <pre className="sql">{text}</pre>
      {long ? (
        <button type="button" className="linkish overflow-toggle" onClick={() => setOpen((v) => !v)}>
          {open ? "收起 SQL" : `展开全部 ${lines.length} 行`}
        </button>
      ) : null}
    </>
  );
}

export function OverflowTable({
  columns,
  rows,
}: {
  columns: string[];
  rows: unknown[][];
}) {
  const [open, setOpen] = useState(false);
  const long = rows.length > TABLE_MAX_ROWS;
  const shown = !long || open ? rows : rows.slice(0, TABLE_MAX_ROWS);
  return (
    <>
      <div className="table-wrap">
        <table className="result">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, i) => (
              <tr key={i}>
                {columns.map((_, j) => (
                  <td key={j}>{formatCell(row[j])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {long ? (
        <button type="button" className="linkish overflow-toggle" onClick={() => setOpen((v) => !v)}>
          {open ? "收起表格" : `展开全部 ${rows.length} 行`}
        </button>
      ) : null}
    </>
  );
}
