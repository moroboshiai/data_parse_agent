"""仓库配置。模型与规则阈值都从这里读取。"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class ConfidenceNormalizeSettings(BaseModel):
    """数值 confidence 映射为 low/medium/high 的阈值（左闭区间）。"""

    high_min: float = 0.85
    medium_min: float = 0.55

    @model_validator(mode="after")
    def _check_order(self) -> ConfidenceNormalizeSettings:
        if self.high_min < self.medium_min:
            raise ValueError("confidence.high_min 不能小于 medium_min")
        return self


class LlmSettings(BaseModel):
    enabled: bool = True
    base_url: str = "https://10.4.180.8:7443/21"
    model: str = "TopASK"
    verify_ssl: bool = False
    ca_bundle: str | None = None
    timeout: float = 1800
    max_tokens: int = 20000
    temperature: float = 0
    max_retries: int = 2
    max_calls_per_task: int = 200
    log_calls: bool = True
    confidence_normalize: ConfidenceNormalizeSettings = Field(
        default_factory=ConfidenceNormalizeSettings
    )


class RuleSettings(BaseModel):
    max_sample_rows: int = 20
    max_fields: int = 50
    regex_max_length: int = 500
    batch_size: int = 4
    mapping_batch_fields: int = 20
    rule_version: int = 1
    confidence: ConfidenceNormalizeSettings = Field(default_factory=ConfidenceNormalizeSettings)


_cached_llm: LlmSettings | None = None
_cached_rules: RuleSettings | None = None


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "configs" / "llm.yaml").is_file():
            return candidate
    raise FileNotFoundError("找不到仓库根目录（缺少 configs/llm.yaml）")


def configure_llm(settings: LlmSettings) -> None:
    global _cached_llm
    _cached_llm = settings


def configure_rules(settings: RuleSettings) -> None:
    global _cached_rules
    _cached_rules = settings


def reset_settings_cache() -> None:
    global _cached_llm, _cached_rules
    _cached_llm = None
    _cached_rules = None


def _load_block(path: Path, key: str) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"找不到配置: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"配置格式错误: {path}")
    block = raw.get(key, raw)
    if not isinstance(block, dict):
        raise ValueError(f"配置缺少 {key} 节点: {path}")
    return block


def load_llm_config(path: Path) -> LlmSettings:
    return LlmSettings.model_validate(_load_block(path, "llm"))


def load_rule_config(path: Path) -> RuleSettings:
    return RuleSettings.model_validate(_load_block(path, "rules"))


def get_llm_settings(repo_root: Path | None = None) -> LlmSettings:
    global _cached_llm
    if _cached_llm is not None:
        return _cached_llm
    root = repo_root
    if root is None:
        try:
            root = find_repo_root()
        except FileNotFoundError:
            _cached_llm = LlmSettings()
            return _cached_llm
    path = root / "configs" / "llm.yaml"
    _cached_llm = load_llm_config(path) if path.is_file() else LlmSettings()
    return _cached_llm


def get_rule_settings(repo_root: Path | None = None) -> RuleSettings:
    global _cached_rules
    if _cached_rules is not None:
        return _cached_rules
    root = repo_root
    if root is None:
        try:
            root = find_repo_root()
        except FileNotFoundError:
            _cached_rules = RuleSettings()
            return _cached_rules
    path = root / "configs" / "rules.yaml"
    _cached_rules = load_rule_config(path) if path.is_file() else RuleSettings()
    return _cached_rules


def init_from_repo(repo_root: Path) -> tuple[LlmSettings, RuleSettings]:
    llm_path = repo_root / "configs" / "llm.yaml"
    rule_path = repo_root / "configs" / "rules.yaml"
    llm = load_llm_config(llm_path) if llm_path.is_file() else LlmSettings()
    rules = load_rule_config(rule_path) if rule_path.is_file() else RuleSettings()
    configure_llm(llm)
    configure_rules(rules)
    return llm, rules


def env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}
