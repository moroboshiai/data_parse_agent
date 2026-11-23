# 清洗规则生成

只为已经判定需要清洗的字段生成一条清洗规则。

## 允许的算子

- `trim`：去掉首尾空白。
- `lower` / `upper`：统一大小写。
- `collapse_whitespace`：压缩连续空白。
- `normalize_datetime`：按 `input_formats` 解析，再按 `output_format` 输出。格式使用 Python strftime，例如 `%Y-%m-%d %H:%M:%S`。ISO 8601（`2026-10-14T10:37:39.000+08:00`）可以留空 `input_formats`，执行器会用 `fromisoformat` 解析。不要输出 `yyyy-MM-dd HH:mm:ss` 这类 Java 格式；规范表若写成这种形式，输出仍用 `%Y-%m-%d %H:%M:%S`。

不要输出正则，不要建议未列出的算子，也不要直接修改样本。需要重复执行的规则应保持幂等。
