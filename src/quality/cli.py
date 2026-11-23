"""数据质检命令行。"""

from __future__ import annotations

import argparse
import json

from quality.analyze import run_analyze
from quality.diagnose import run_diagnose
from quality.monitor import run_monitor
from quality.profile_builder import build_profile_from_standard_schema, save_profile
from quality.store import read_json
from table_registration.config import find_repo_root
from table_registration.llm import LlmClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="数据质检智能体")
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze = subparsers.add_parser("analyze", help="按画像分析一段时间的数据质量")
    _add_common(analyze)
    analyze.add_argument("--baseline", default="", help="可选基线 JSON")
    monitor = subparsers.add_parser("monitor", help="与基线对比并记录质量问题")
    _add_common(monitor)
    monitor.add_argument("--baseline", default="", help="基线 JSON，默认写在输出目录")
    monitor.add_argument("--repo", default="", help="解析规则仓库目录，诊断时读取")
    diagnose = subparsers.add_parser("diagnose", help="诊断一条已经保存的质量问题")
    diagnose.add_argument("--issue", required=True, help="质量问题 JSON")
    diagnose.add_argument("--output", default="")
    diagnose.add_argument("--repo", default="")
    init = subparsers.add_parser("init-profile", help="从 data/standard_schema 规范表生成质量画像草稿")
    init.add_argument("--standard", required=True, help="规范表 JSON，如 data/standard_schema/dns_schema.json")
    init.add_argument("--source-id", default="", help="来源标识，默认使用 category_alias")
    init.add_argument("--category", default="", help="规则包分类，默认与 category_alias 一致")
    init.add_argument(
        "--output",
        default="",
        help="输出画像路径，默认为 data/quality/profiles/<source_id>.json",
    )
    init.add_argument("--rules", default="", help="规则包根目录，默认使用内置规则")
    init.add_argument("--no-link-rules", action="store_true", help="不根据已有规则包填写 check_rules")
    args = parser.parse_args(argv)
    output = args.output or str(find_repo_root() / "data" / "quality")
    try:
        if args.command == "analyze":
            report = run_analyze(
                profile_path=args.profile,
                input_path=args.input,
                llm=LlmClient(),
                output_dir=output,
                start=args.start,
                end=args.end,
                baseline_path=args.baseline,
                rules_root=args.rules or None,
            )
            print(json.dumps(_analyze_summary(report, output), ensure_ascii=False, indent=2))
            return 0
        if args.command == "monitor":
            result = run_monitor(
                profile_path=args.profile,
                input_path=args.input,
                llm=LlmClient(),
                output_dir=output,
                start=args.start,
                end=args.end,
                baseline_path_value=args.baseline,
                repository=args.repo,
                rules_root=args.rules or None,
            )
            print(json.dumps({"source_id": result.get("source_id"), "issue_count": result.get("issue_count"), "output": output}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "init-profile":
            profile = build_profile_from_standard_schema(
                args.standard,
                source_id=args.source_id,
                category=args.category,
                rules_root=args.rules or None,
                link_rules=not args.no_link_rules,
            )
            root = find_repo_root()
            source_id = str(profile.get("source_id") or "profile")
            out_path = args.output or str(root / "data" / "quality" / "profiles" / f"{source_id}.json")
            save_profile(out_path, profile)
            print(
                json.dumps(
                    {
                        "source_id": profile.get("source_id"),
                        "category": profile.get("category"),
                        "field_count": len(profile.get("fields") or []),
                        "profile_path": out_path,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        result = run_diagnose(issue=read_json(args.issue), llm=LlmClient(), output_dir=output, repository=args.repo or None)
        task = result.get("task") or {}
        print(json.dumps({"issue_id": task.get("issue_id"), "target_agent": task.get("target_agent"), "output": output}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", required=True, help="质量画像 JSON")
    parser.add_argument("--input", required=True, help="CSV 或 JSONL")
    parser.add_argument("--output", default="")
    parser.add_argument("--start", default="", help="开始时间，日期按当天包含")
    parser.add_argument("--end", default="", help="结束时间，纯日期按当天结束")
    parser.add_argument("--rules", default="", help="规则包根目录，默认使用内置规则")


def _analyze_summary(report: dict, output: str) -> dict:
    return {
        "report_id": report.get("report_id"),
        "source_id": report.get("source_id"),
        "category": report.get("category"),
        "quality_status": report.get("quality_status"),
        "issue_count": len(report.get("issues") or []),
        "output": output,
    }


if __name__ == "__main__":
    raise SystemExit(main())
