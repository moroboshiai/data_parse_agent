"""业务约束入口。"""

from table_registration.rules.engine import RULES, MappingIsolationError

__all__ = ["RULES", "MappingIsolationError"]
