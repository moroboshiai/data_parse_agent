"""数据治理主控。串联表注册、解析、质检和富化，不代替各阶段做判断。"""

from governance.runner import Orchestrator

__all__ = ["Orchestrator"]
