# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

QueryPilot is an AI-native natural-language-to-SQL agent for customer marketing scenarios (NJU competition project). Users ask questions in Chinese; the system prunes schema, generates SQL via a single LLM call, validates it through a dual-layer safety fence, and executes against a local DuckDB database.

**Architecture**: Metadata Engine (YAML knowledge) → Agent Pipeline (prune → generate → safety → execute) → Eval (Execution Match).

## Key Commands

```bash
# Ask a question (main entry point)
querypilot ask "有多少年龄大于30岁的女性客户？"
# or: python -m querypilot.cli ask "..."

# Batch eval against gold-standard Q&A
querypilot eval --path "data/Q&A.xlsx" --output logs/eval_reports/out.json

# Run eval on Extra sets (generalization), fs=3 or fs=0
python -m querypilot.cli eval --path "data/extra/Q&A_all.xlsx" --paths "data/extra2/Q&A_all.xlsx" --no-exact-few-shot --max-few-shots 3 --workers 4 --output logs/eval_reports/out.json

# Benchmark (cold/warm)
python scripts/bench_pipeline.py --limit 3 --warm --output logs/perf_reports/bench.json

# Start HTTP API
querypilot serve --host 127.0.0.1 --port 8000

# Start Chat UI (frontend/; PowerShell: run lines separately, not &&)
cd frontend
npm install
npm run dev

# Tests
pytest -q

# Import CSV data into DuckDB
python scripts/import_data.py
```

## Critical Conventions

- **Cross-table joins**: default to `pty_id` / `org_id` only. **Do NOT** add `data_dt` as a join key — dimension tables and fact tables have misaligned date sets.
- **`dim_public` usage**: always filter on both `code` AND `code_type_id` (same `code` can belong to different encoding types).
- **Metadata access**: use `load_metadata()` from `querypilot.metadata_engine` (public entry). Pipeline hot path may use `get_metadata()` from `querypilot.cache` — never read YAML under `metadata/` directly.
- **`data/` directory**: read-only CSVs. Never modify source data.
- **`.env`**: contains `DEEPSEEK_API_KEY`; never commit.
- **Safety fence**: L1 (sqlglot AST) blocks writes/unauthorized tables and fixes column hallucinations; L2 (`EXPLAIN`) catches DB-level errors with 1-shot LLM correction (max 1 retry).

## Code Structure

| Directory | Purpose |
|-----------|---------|
| `querypilot/agent/` | Core pipeline (`pipeline.py` → `ask()`), prompt assembly, SQL generation, deterministic fixes (`topn_fix.py`, `pnl_fix.py`) |
| `querypilot/metadata_engine/` | YAML loading, schema pruning, join-graph, metrics, value descriptors |
| `querypilot/safety/` | L1 AST guard (`l1_ast.py`), L2 EXPLAIN (`l2_explain.py`), result probe |
| `querypilot/eval/` | Execution Match engine, eval runner, eval-agent (error attribution), dataset loading |
| `querypilot/cache/` | In-process metadata/prune/query cache; optional Redis backend (`REDIS_URL`) |
| `querypilot/llm/` | DeepSeek client |
| `querypilot/db/` | DuckDB connection (read-only) |
| `querypilot/api/` | FastAPI wrapper around `ask()` |
| `metadata/` | YAML configs: tables, metrics, join_graph, value_descriptors, few_shots |
| `data/` | Source CSVs and Q&A Excel files (read-only) |
| `logs/` | Per-phase experiment logs and eval/perf reports |
| `scripts/` | Operational scripts (import, benchmark, demo, eval baseline) |
| `frontend/` | Vite + React chat UI |

## Environment

- **Runtime**: Python 3.10+ (`requires-python` in `pyproject.toml`), dependencies in `pyproject.toml` / `requirements.txt`
- **Database**: DuckDB (local file at `db/competition.duckdb`, typically gitignored)
- **LLM**: DeepSeek API (key in `.env`)
- **Platform**: Windows (PowerShell); some scripts have Windows-specific notes

## Where to Find Details

- Agent coding principles (mandatory): `AGENTS.md`
- Competition requirements & overall plan: `README.md`
- Design overview & architecture narrative: `logs/Summary.md`
- Per-phase implementation logs: `logs/01-*` through `logs/05-*`
- Eval reports: `logs/eval_reports/`
- Performance reports: `logs/perf_reports/`
