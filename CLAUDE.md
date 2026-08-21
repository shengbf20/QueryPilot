# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

QueryPilot is an AI-native natural-language-to-SQL agent for customer marketing scenarios (NJU competition project). Users ask questions in Chinese; the system may refuse malicious intent, prune schema, generate SQL via a single LLM call (or return `stage=clarify` if the ask is underspecified), validates it through a dual-layer safety fence, and executes against a local DuckDB database.

**Architecture**: Metadata Engine (YAML knowledge) → Agent Pipeline (intent → prune → generate / clarify → L1/L2 → execute) → Eval (Execution Match; Extra3 = refuse + warning). Parallel **strong-agent** path: `querypilot.agentic.run` (tool loop + session memory). Do not fold agentic orchestration into `ask()`.

## Key Commands

```bash
# Ask a question (main entry point; fast pipeline)
querypilot ask "有多少年龄大于30岁的女性客户？"
# Strong-agent tool loop (chat UI / --mode agent)
querypilot ask --mode agent "帮我看看客户情况"

# Batch eval against gold-standard Q&A
querypilot eval --path "data/Q&A.xlsx" --output logs/eval_reports/out.json
# Strong-agent gold eval (does not call ask())
querypilot eval --mode agent --path "data/Q&A.xlsx" --workers 4 --output logs/eval_reports/eval_agent_gold.json

# Run eval on Extra sets (generalization), fs=3 or fs=0
python -m querypilot.cli eval --path "data/extra/Q&A_all.xlsx" --paths "data/extra2/Q&A_all.xlsx" --no-exact-few-shot --max-few-shots 3 --workers 4 --output logs/eval_reports/out.json

# Extra3 safety eval (refuse + warning = pass)
querypilot eval --path "data/extra3/Q&A_all.xlsx" --output logs/eval_reports/extra3_safety.json

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
- **Safety fence**: intent guard (`intent_guard.py`) refuses destructive / jailbreak questions before prune (`stage=safety`); L1 (sqlglot AST) blocks writes/unauthorized tables and fixes column hallucinations; L2 (`EXPLAIN`) catches DB-level errors with 1-shot LLM correction (max 1 retry).
- **Clarify / history**: underspecified questions return `ok=True`, empty SQL, `stage=clarify`. Pass `history=[{role, content}]` on the next `ask()`; CLI TTY follows up unless `--no-followup`. Do not use query cache or exact few-shot when `history` is present.

## Code Structure

| Directory | Purpose |
|-----------|---------|
| `querypilot/agent/` | Core pipeline (`pipeline.py` → `ask()`), prompt assembly, SQL generation, deterministic fixes (`topn_fix.py`, `pnl_fix.py`) |
| `querypilot/agentic/` | Strong-agent runtime (`run()`): budgeted tools + session memory; does not call `ask()` |
| `querypilot/metadata_engine/` | YAML loading, schema pruning, join-graph, metrics, value descriptors |
| `querypilot/safety/` | Intent guard (`intent_guard.py`), L1 AST (`l1_ast.py`), L2 EXPLAIN (`l2_explain.py`), result probe |
| `querypilot/eval/` | Execution Match, Extra3 safety match (`safety_match.py`), eval runner, eval-agent, dataset loading |
| `querypilot/cache/` | In-process metadata/prune/query cache; optional Redis backend (`REDIS_URL`) |
| `querypilot/llm/` | DeepSeek client |
| `querypilot/db/` | DuckDB connection (read-only) |
| `querypilot/api/` | FastAPI wrapper around `ask()` |
| `metadata/` | YAML configs: tables, metrics, join_graph, value_descriptors, few_shots |
| `data/` | Source CSVs and Q&A Excel (official / extra / extra2 / extra3; read-only) |
| `logs/` | Per-phase experiment logs and eval/perf reports |
| `scripts/` | Operational scripts (import, benchmark, demo, eval baseline) |
| `frontend/` | Vite + React UI: lab（问数）+ chat（对话） |

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
