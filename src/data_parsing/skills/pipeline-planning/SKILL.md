# Pipeline 规划

根据程序给出的字段库存事实和 `allowed_actions`，为每个字段选择一个下一步动作。

只能选择该字段 `allowed_actions` 中的动作。不要发明新动作，不要指定规则状态，不要输出 Python 代码，不要调用工具。

## 动作

- `passthrough`：直通，不生成规则。
- `use_existing`：使用本表已有规则。
- `reuse_generic`：判断通用规则能否复用。
- `use_seeded`：使用注册阶段种入且已通过测试的规则。
- `generate`：生成新规则。
- `human_review`：交给人工。
- `return_to_registration`：退回表注册，不改映射。
