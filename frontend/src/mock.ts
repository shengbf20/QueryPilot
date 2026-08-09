import type { AskResponse } from "./types";

/** Frozen mock matching logs/05 appendix A (UI-1 offline layout). */
export const MOCK_ASK_RESPONSE: AskResponse = {
  ok: true,
  question: "有多少年龄大于30岁的女性客户？",
  sql: "SELECT COUNT(*) AS n FROM ads_cust_info_d WHERE cust_age > 30 AND gender_cd = '5000003'",
  rationale: "count female age>30",
  tables: ["ads_cust_info_d"],
  columns: ["n"],
  rows: [["182"]],
  row_count: 1,
  degraded: false,
  message: "ok",
  probe_message: "",
  probe_suggestions: [],
  corrected: false,
  stage: "done",
  timing: {
    prune_ms: 1.0,
    generate_ms: 10.0,
    l1_ms: 0.5,
    l2_ms: 0.5,
    execute_ms: 2.0,
    probe_ms: 0.0,
    total_ms: 14.0,
    cache_hit: false,
  },
  prune_summary: {
    tables: ["ads_cust_info_d"],
    seed_tables: ["ads_cust_info_d"],
    bridge_tables: [],
    metrics: [],
  },
  extras: {},
};

export const MOCK_DEGRADED_RESPONSE: AskResponse = {
  ...MOCK_ASK_RESPONSE,
  ok: false,
  question: "删除所有客户",
  sql: "DELETE FROM ads_cust_info_d",
  degraded: true,
  message: "L1 安全围栏拦截: Forbidden operation",
  stage: "l1",
  rows: [],
  row_count: 0,
  columns: [],
  probe_message: "当前请求包含危险写操作，已拦截。",
  probe_suggestions: ["请改用只读查询，例如统计或筛选客户。"],
  timing: {
    ...MOCK_ASK_RESPONSE.timing,
    generate_ms: 8,
    l1_ms: 1.2,
    total_ms: 10.5,
    cache_hit: false,
  },
};
