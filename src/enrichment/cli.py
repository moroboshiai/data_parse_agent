"""富化命令行。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from enrichment.batch import run_batch
from enrichment.investigation import run_investigation
from enrichment.knowledge import KnowledgeBase
from enrichment.schemas import STRATEGY_VERSION
from table_registration.config import find_repo_root
from table_registration.llm import LlmClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="数据富化智能体")
    subparsers = parser.add_subparsers(dest="command", required=True)
    batch = subparsers.add_parser("batch", help="批量富化标准化事件")
    batch.add_argument("--input", required=True, help="解析 JSONL。进入规则前会补 event_id，并把整数 IPv4 转为点分地址")
    batch.add_argument("--knowledge", required=True, help="资产、情报和历史知识目录")
    batch.add_argument("--output", help="富化结果目录，默认 data/enrichment")
    investigate = subparsers.add_parser("investigate", help="调查单条标准化事件")
    investigate.add_argument("--event", required=True, help="单条标准事件 JSON")
    investigate.add_argument("--knowledge", required=True, help="资产、情报和历史知识目录")
    investigate.add_argument("--output", help="调查报告目录，默认 data/enrichment")
    args = parser.parse_args(argv)
    output = args.output or str(find_repo_root() / "data" / "enrichment")
    if args.command == "batch":
        source = Path(args.input)
        if not source.is_file():
            print(json.dumps({"error": "输入文件不存在"}, ensure_ascii=False))
            return 1
        records = run_batch(
            events=_load_jsonl(source),
            knowledge=KnowledgeBase(args.knowledge),
            llm=LlmClient(),
            output_dir=output,
            strategy_version=STRATEGY_VERSION,
        )
        print(json.dumps({"count": len(records), "output": output, "strategy_version": STRATEGY_VERSION}, ensure_ascii=False, indent=2))
        return 0
    event_path = Path(args.event)
    if not event_path.is_file():
        print(json.dumps({"error": "事件文件不存在"}, ensure_ascii=False))
        return 1
    report = run_investigation(
        event=json.loads(event_path.read_text(encoding="utf-8")),
        knowledge=KnowledgeBase(args.knowledge),
        llm=LlmClient(),
        output_dir=output,
    )
    print(json.dumps({"event_id": report.get("event_id"), "investigation_status": report.get("investigation_status"), "output": output}, ensure_ascii=False, indent=2))
    return 0


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if isinstance(item, dict):
            rows.append(item)
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
