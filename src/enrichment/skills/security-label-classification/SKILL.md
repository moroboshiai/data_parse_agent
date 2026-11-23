# 安全标签判断

只判断程序给出的候选风险标签是否成立。

事实标签已经由程序根据资产库和情报库确定，不要修改事实，不要新增候选名单以外的标签，不要把资产属性写成风险结论。

有知识证据时，每条成立的标签必须引用输入里已经存在的 evidence_id。没有证据时判定为 insufficient 或 reject。域名看起来可疑本身不能作为证据。

当事件的 label_without_knowledge 为 true 时，知识库没有可用数据。只根据事件字段判断候选标签是否可能成立。accept 表示事件内容支持该标签，evidence_ids 留空。不要因为缺少情报就把全部标签判为 insufficient。

三个候选互相独立。一条事件可以只成立其中一个，也可以都不成立。正常业务域名应 reject。不要因为同一条事件里有一个标签成立，就把另外两个也写成 accept。

decision 只能是 accept、reject、insufficient。不要输出标签生效状态。
