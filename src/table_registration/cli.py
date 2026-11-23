"""命令行入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from table_registration.config import find_repo_root
from table_registration.graph import run_registration
from table_registration.tools.candidate_store import confirm_candidate
from table_registration.tools.mapping_memory import MappingMemory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="表注册智能体")
    subparsers = parser.add_subparsers(dest="command", required=True)

    register = subparsers.add_parser("register", help="生成候选映射规则")
    register.add_argument("--sample", required=True, help="来源表样本，支持 CSV、JSON、XLSX")
    register.add_argument("--standard", required=True, help="规范表结构 JSON")
    register.add_argument("--source-schema", help="来源表结构说明，JSON 或文本")
    register.add_argument("--source-name", default="source_table")
    register.add_argument("--candidate-dir")
    register.add_argument("--memory")

    confirm = subparsers.add_parser("confirm", help="确认候选规则并写入历史映射")
    confirm.add_argument("--candidate", required=True)
    confirm.add_argument("--memory")

    args = parser.parse_args(argv)
    root = find_repo_root()
    memory = args.memory or str(root / "data" / "mapping_memory.json")
    if args.command == "register":
        schema_path, schema_text = _split_source_schema(args.source_schema)
        state = run_registration(
            sample_path=args.sample,
            source_schema=schema_text,
            source_schema_path=schema_path,
            standard_schema_path=args.standard,
            source_name=args.source_name,
            memory_path=memory,
            candidate_dir=args.candidate_dir,
            repo_root=root,
        )
        _print_state(state)
        return 0 if state.get("status") != "failed" else 1
    document = confirm_candidate(args.candidate, MappingMemory(memory))
    print(json.dumps({"status": document["status"], "candidate": str(args.candidate)}, ensure_ascii=False))
    return 0


def _split_source_schema(path: str | None) -> tuple[str | None, str | None]:
    if not path:
        return None, None
    source = Path(path)
    if source.suffix.lower() in {".txt", ".md"}:
        return None, source.read_text(encoding="utf-8")
    return str(source), None


def _print_state(state: dict) -> None:
    summary = {
        "status": state.get("status"),
        "candidate_path": state.get("candidate_path") or "",
        "mapping_mode": state.get("mapping_mode") or "",
        "errors": state.get("errors") or [],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
