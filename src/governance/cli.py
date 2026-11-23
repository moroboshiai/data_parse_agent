"""治理主控命令行。"""

from __future__ import annotations

import argparse
import json

from governance.runner import Orchestrator
from governance.store import GovernanceError
from table_registration.config import find_repo_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="数据治理主控智能体")
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start", help="登记一条治理任务")
    start.add_argument("--sample", required=True)
    start.add_argument("--standard", required=True)
    start.add_argument("--source-name", required=True)
    start.add_argument("--input", default="")
    start.add_argument("--knowledge", default="")
    for name, help_text in (
        ("step", "执行一个自动阶段"),
        ("run", "连续执行到人工确认、失败或复核"),
        ("status", "查看阶段、产物和阻塞原因"),
        ("confirm", "确认候选并继续"),
        ("resume", "从当前阶段继续"),
    ):
        item = subparsers.add_parser(name, help=help_text)
        item.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    root = find_repo_root()
    agent = Orchestrator(repo_root=root, work_root=root)
    try:
        if args.command == "start":
            run = agent.start(
                sample_path=args.sample,
                standard_schema_path=args.standard,
                source_name=args.source_name,
                input_path=args.input,
                knowledge_path=args.knowledge,
            )
        elif args.command == "step":
            run = agent.step(args.run_id)
        elif args.command == "run":
            run = agent.run(args.run_id)
        elif args.command == "confirm":
            run = agent.confirm(args.run_id)
        elif args.command == "resume":
            run = agent.resume(args.run_id)
        else:
            run = agent.status(args.run_id)
    except (GovernanceError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    if args.command == "status":
        print(json.dumps(run, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(agent.status(run["run_id"]), ensure_ascii=False, indent=2))
    return 0 if run.get("status") != "blocked" and run.get("stage") != "blocked" else 1
