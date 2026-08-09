/** API-1 response contract (aligned with PipelineResult.to_api_dict). */

export type StageTiming = {
  prune_ms: number;
  generate_ms: number;
  l1_ms: number;
  l2_ms: number;
  execute_ms: number;
  probe_ms: number;
  total_ms: number;
  cache_hit: boolean;
};

export type PruneSummary = {
  tables: string[];
  seed_tables: string[];
  bridge_tables: string[];
  metrics: string[];
};

export type AskResponse = {
  ok: boolean;
  question: string;
  sql: string;
  rationale: string;
  tables: string[];
  columns: string[];
  rows: unknown[][];
  row_count: number;
  degraded: boolean;
  message: string;
  probe_message: string;
  probe_suggestions: string[];
  corrected: boolean;
  stage: string;
  timing: StageTiming;
  prune_summary: PruneSummary;
  extras: Record<string, unknown>;
};
