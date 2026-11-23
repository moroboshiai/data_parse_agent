"""数据解析命令行。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_parsing.builder import build_pipeline
from data_parsing.learning import learn_from_events
from data_parsing.repository import RuleRepository
from data_parsing.runtime import ParsingEngine, failure_rates, write_jsonl
from table_registration.config import find_repo_root, init_from_repo
from table_registration.llm import LlmClient
from table_registration.tools.candidate_store import load_candidate
from table_registration.tools.file_parser import parse_table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="数据解析智能体")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="根据已确认注册结果构建 Pipeline")
    build.add_argument("--candidate", required=True)
    build.add_argument("--sample", required=True)
    build.add_argument("--source-type", default="generic")
    build.add_argument("--repo")

    parse = subparsers.add_parser("parse", help="按 Pipeline 解析数据")
    parse.add_argument("--pipeline-id", required=True)
    parse.add_argument("--input", required=True)
    parse.add_argument("--output")
    parse.add_argument("--repo")

    learn = subparsers.add_parser("learn", help="根据解析异常优化规则")
    learn.add_argument("--pipeline-id", required=True)
    learn.add_argument("--repo")

    publish = subparsers.add_parser("publish", help="发布灰度规则")
    publish.add_argument("--rule-id", required=True)
    publish.add_argument("--version", required=True, type=int)
    publish.add_argument("--metrics")
    publish.add_argument("--repo")

    rollback = subparsers.add_parser("rollback", help="回滚到指定规则版本")
    rollback.add_argument("--rule-id", required=True)
    rollback.add_argument("--version", required=True, type=int)
    rollback.add_argument("--repo")

    args = parser.parse_args(argv)
    root = find_repo_root()
    repository = RuleRepository(args.repo or root / "data" / "rule_repository")
    if args.command == "build":
        init_from_repo(root)
        pipeline = build_pipeline(
            candidate=load_candidate(args.candidate),
            sample_rows=parse_table(args.sample),
            source_type=args.source_type,
            llm=LlmClient(),
            repository=repository,
        )
        print(json.dumps({"pipeline_id": pipeline["pipeline_id"], "status": pipeline["status"]}, ensure_ascii=False, indent=2))
        return 0 if pipeline["status"] != "failed" else 1
    if args.command == "parse":
        pipeline = repository.get_pipeline(args.pipeline_id)
        result = ParsingEngine(repository).parse(parse_table(args.input), pipeline)
        output = args.output or str(root / "outputs" / "parsed" / f"{args.pipeline_id}.jsonl")
        write_jsonl(output, result["rows"])
        repository.add_events(result["events"])
        print(json.dumps({"output": output, "events": len(result["events"]), "metrics": failure_rates(result["metrics"])}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "learn":
        init_from_repo(root)
        summary = learn_from_events(repository=repository, pipeline_id=args.pipeline_id, llm=LlmClient())
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.command == "publish":
        metrics = json.loads(Path(args.metrics).read_text(encoding="utf-8")) if args.metrics else None
        rule = repository.publish(args.rule_id, args.version, metrics=metrics)
        print(json.dumps({"rule_id": rule["rule_id"], "active_version": rule["active_version"]}, ensure_ascii=False))
        return 0
    rule = repository.rollback(args.rule_id, args.version)
    print(json.dumps({"rule_id": rule["rule_id"], "active_version": rule["active_version"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
