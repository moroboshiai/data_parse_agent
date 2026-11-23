# 解析规则生成

根据一个数据质量问题模板生成一条解析规则。

operator 只能是 passthrough、extract_regex、extract_ip、extract_domain、trim、replace、normalize_time、normalize_ipv4、convert_type、collapse_whitespace、lower、upper、mark_invalid。`normalize_ipv4` 把 32 位整数 IPv4 转为点分地址；解析引擎也会对 `_ip` 字段和 `dns_a` 自动做这一步。

params 只放该算子需要的参数，例如 pattern、group、input_formats、output_format。时间格式使用 Python strftime，例如 `%Y-%m-%d %H:%M:%S`。ISO 8601 可以不填 `input_formats`。不要输出可执行代码，不要设置生效状态。
