"""新表登记问答 CLI（logs/08 §五「人类唯一接触的界面」）。

流程：问卷（A9）→ 答案（命令行 flags，交互式补问缺项）→ 落盘（A5）
      → 注册表同步（A6）→ 校验与回归（A7/A8）。

用法示例:
  python -m querypilot.table_ops.cli questionnaire dwd_new_table_d
  python -m querypilot.table_ops.cli register dwd_new_table_d \
      --alias 新表 --description "……" --granularity 客户级 \
      --col-desc pty_id=客户号 --edge pty_id:ads_cust_info_d.pty_id:fact \
      --cue 触发词1,触发词2 --question "冒烟问句" --yes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from querypilot.table_ops.prompts import (
    format_questionnaire,
    generate_questionnaire,
    mechanical_questionnaire,
)
from querypilot.table_ops.register import RegistrationAnswers, register_table, verify_registration


def _parse_col_desc(pairs: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit(f"--col-desc 需要 col=desc 格式: {pair}")
        col, desc = pair.split("=", 1)
        out[col.strip()] = desc.strip()
    return out


def _parse_edges(specs: list[str] | None) -> list[dict[str, Any]]:
    """--edge 列:目标表.目标列[:边类型[:规则,规则]] （边类型默认 dimension）。"""
    edges: list[dict[str, Any]] = []
    for spec in specs or []:
        parts = spec.split(":")
        if len(parts) < 2 or "." not in parts[1]:
            raise SystemExit(f"--edge 需要 列:目标表.目标列[:类型[:规则]] 格式: {spec}")
        column, target = parts[0], parts[1]
        target_table, target_column = target.rsplit(".", 1)
        edge_type = parts[2] if len(parts) > 2 and parts[2] else "dimension"
        rules = parts[3].split(",") if len(parts) > 3 and parts[3] else []
        edge: dict[str, Any] = {
            "id": f"{_CURRENT_TABLE[0]}_to_{target_table}",
            "from": _CURRENT_TABLE[0],
            "to": target_table,
            "type": edge_type,
            "join": {column: target_column},
        }
        if rules:
            edge["rules"] = rules
        edges.append(edge)
    return edges


_CURRENT_TABLE: list[str] = [""]  # --edge 的 id/from 由当前表名填充


def _build_answers(args: argparse.Namespace) -> RegistrationAnswers:
    _CURRENT_TABLE[0] = args.table
    return RegistrationAnswers(
        table=args.table,
        alias=args.alias or "",
        description=args.description or "",
        domain=args.domain or "",
        granularity=args.granularity or "",
        primary_key=args.primary_key.split(",") if args.primary_key else None,
        column_descriptions=_parse_col_desc(args.col_desc),
        column_aliases={
            pair.split("=", 1)[0].strip(): [
                a.strip() for a in pair.split("=", 1)[1].split(",") if a.strip()
            ]
            for pair in args.col_alias or []
            if "=" in pair
        },
        join_edges=_parse_edges(args.edge),
        enum_meanings={
            pair.split("=", 1)[0].strip(): {
                kv.split(":", 1)[0]: kv.split(":", 1)[1]
                for kv in pair.split("=", 1)[1].split(",")
                if ":" in kv
            }
            for pair in args.enum_meaning or []
            if "=" in pair
        },
        usage=args.usage or [],
        notes=args.note or [],
        cue_words=[c for c in (args.cue.split(",") if args.cue else []) if c],
    )


def _interactive_fill(answers: RegistrationAnswers) -> RegistrationAnswers:
    """TTY 下对缺失的关键语义字段补问（非 TTY 直接返回，缺项由骨架兜底）。"""
    if not sys.stdin.isatty():
        return answers

    def ask(prompt: str, current: str) -> str:
        suffix = f" [{current}]" if current else ""
        value = input(f"{prompt}{suffix}: ").strip()
        return value or current

    alias = ask("Q1 表别名", answers.alias)
    description = ask("Q1 表用途描述", answers.description)
    granularity = ask("Q3 一行代表什么", answers.granularity)
    cue = ask("A5 触发词（逗号分隔）", ",".join(answers.cue_words))
    return RegistrationAnswers(
        table=answers.table,
        alias=alias,
        description=description,
        domain=answers.domain,
        granularity=granularity,
        primary_key=answers.primary_key,
        column_descriptions=answers.column_descriptions,
        column_aliases=answers.column_aliases,
        join_edges=answers.join_edges,
        enum_meanings=answers.enum_meanings,
        usage=answers.usage,
        notes=answers.notes,
        cue_words=[c for c in cue.split(",") if c],
    )


def cmd_questionnaire(args: argparse.Namespace) -> int:
    questionnaire = (
        generate_questionnaire(args.table) if args.llm else mechanical_questionnaire(args.table)
    )
    if args.json:
        import json

        print(json.dumps(questionnaire, ensure_ascii=False, indent=2))
    else:
        print(format_questionnaire(questionnaire))
    return 0


def cmd_register(args: argparse.Namespace) -> int:
    metadata_dir = Path(args.metadata_dir) if args.metadata_dir else None

    if not args.yes:
        print(format_questionnaire(mechanical_questionnaire(args.table)))
        print("\n--- 请核对以上候选，通过 flags 提供答案（--help 查看格式）---")

    answers = _build_answers(args)
    if not args.yes:
        answers = _interactive_fill(answers)

    result = register_table(
        answers, metadata_dir=metadata_dir, dry_run=args.dry_run, force=args.force
    )
    print(result.table_yaml)
    if result.dry_run:
        print(f"[dry-run] 未写盘；join_graph 追加:\n{result.join_graph_insert}")
        print(f"[dry-run] pruning 追加:\n{result.pruning_insert}")
        return 0

    print(f"已写入: {result.table_yaml_path}")
    print(f"已更新: {result.join_graph_path}, {result.pruning_path}")
    if result.value_descriptors_insert:
        print(f"已更新: {result.value_descriptors_path}")

    # A6 注册表同步
    sync = verify_registration(args.table, metadata_dir=metadata_dir)
    print("\n" + sync.report())
    if not sync.ok:
        return 1

    # A7/A8 回归
    from querypilot.table_ops.validate import run_onboarding_regression

    regression = run_onboarding_regression(
        args.table,
        smoke_questions=args.question,
        metadata_dir=metadata_dir,
    )
    print("\n" + regression.report())
    return 0 if regression.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m querypilot.table_ops.cli",
        description="新表登记问答入口（问卷 → 答案 → 落盘 → 同步 → 回归）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_q = sub.add_parser("questionnaire", help="打印新表登记问卷（A9）")
    p_q.add_argument("table")
    p_q.add_argument("--json", action="store_true", help="输出 JSON")
    p_q.add_argument("--llm", action="store_true", help="LLM 翻译问卷（默认机械问卷）")
    p_q.set_defaults(func=cmd_questionnaire)

    p_r = sub.add_parser("register", help="问卷答案落盘 + 同步验证 + 回归")
    p_r.add_argument("table")
    p_r.add_argument("--alias", default=None)
    p_r.add_argument("--description", default=None)
    p_r.add_argument("--domain", default=None)
    p_r.add_argument("--granularity", default=None)
    p_r.add_argument("--primary-key", default=None, help="逗号分隔（默认用骨架建议）")
    p_r.add_argument("--col-desc", action="append", default=None, help="列=含义（可多次）")
    p_r.add_argument("--col-alias", action="append", default=None, help="列=别名1,别名2（可多次）")
    p_r.add_argument(
        "--edge",
        action="append",
        default=None,
        help="列:目标表.目标列[:类型[:规则]]（可多次；类型 fact/dimension/lookup）",
    )
    p_r.add_argument("--enum-meaning", action="append", default=None, help="列=值:含义,值:含义（可多次）")
    p_r.add_argument("--usage", action="append", default=None)
    p_r.add_argument("--note", action="append", default=None)
    p_r.add_argument("--cue", default=None, help="剪枝触发词，逗号分隔（A5）")
    p_r.add_argument("--question", action="append", default=None, help="剪枝冒烟问句（可多次）")
    p_r.add_argument("--metadata-dir", default=None, help="元数据目录（默认 metadata/）")
    p_r.add_argument("--dry-run", action="store_true", help="只渲染不写盘")
    p_r.add_argument("--force", action="store_true", help="允许覆盖已存在的表 YAML")
    p_r.add_argument(
        "--yes", action="store_true", help="跳过问卷打印直接落盘（脚本化 / 已核对）"
    )
    p_r.set_defaults(func=cmd_register)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
