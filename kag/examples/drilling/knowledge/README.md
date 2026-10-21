# 本地公开数据知识库

来源目录：`D:/drilling_agent_data`。原文件保持不变；项目只保存导入代码、来源指纹和使用边界，原数据与生成内容不上传 GitHub。

首批内容：

- Volve 第三方 DDR 镜像：只接入已有划分中的 F-11 T2 开发井，53份日报、493条作业记录。保存报告时段、发生时段、原文定位、原始状态与候选筛查类别；类别命中不等于确认异常或根因。验证和测试井保留在原目录。
- Azadegan：核对65376条深度记录，导入字段、原始五类标签分布、缺测和公式缓存统计。没有井号和绝对时间；记录数不能当事故数。[论文与附件](https://link.springer.com/article/10.1007/s42452-021-04769-0)。
- Marun：核对2820条记录，导入字段、连续漏失率范围和缺测统计；保持原回归任务，未另造分类标签。[发布者数据页](https://data.mendeley.com/datasets/hr7hbxdryp/1)。

两份数值工作簿保留在源目录，首批入图的是数据说明与实测统计，没有把每行数值变成因果知识。3W生产异常、无明确标签或许可的候选数据、评测包与实验产物不入首批诊断知识库。

```powershell
uv pip install --python .venv/Scripts/python.exe -r deploy/local/requirements-knowledge.txt
.venv/Scripts/python.exe kag/examples/drilling/knowledge_import.py
.venv/Scripts/python.exe kag/examples/drilling/knowledge_import.py --write
```

第一条 Python 命令只校验和准备；`--write` 同步业务 Schema，通过 KAG 向量化与写入组件构建 `KnowledgeDataset → DrillingRecord → Wellbore/日报/Chunk` 关系，随后从 OpenSPG 回读节点和关系。不修改 KAG 框架，也不调用对话模型猜测结构化字段。

向量使用已配置的本地模型。稳定ID支持同一批数据重复写入；源文件SHA-256不匹配、开发井划分不明确或图谱回读缺失时停止，不能把导入接口成功当作唯一验收。

导入结果：`results/knowledge/import.json`。成功后工作台“资料目录”可浏览、搜索原文，现有问答可检索新片段；`GET /api/knowledge` 查看最近成功导入信息。新增3类业务实体、552个检索片段；保留原有诊断规则，新增记录没有自动转成已核实观测。

混合模式增加 KAG 注册检索器 `record_retriever.py`：对明确的 F-11 T2 井号与单一米制深度，沿“井筒—记录—原文”查询；没有命中时继续原有检索。纯向量模式保持独立，用于对照。首次实测中，纯向量未找到3058 m遇阻原文，混合模式能定位20 MT超拉记录，并保留报告中3008 m/3058 m的记载差异。它是当前固定数据上的查证示例，不是通用诊断准确率。

复测三题：`.venv/Scripts/python.exe kag/examples/drilling/evaluate.py --cases kag/examples/drilling/knowledge/benchmark.json --mode hybrid --output kag/examples/drilling/results/knowledge/evaluation.json`。验收规则只检查关键词、来源与引用编号，仍需核查回答语义。

这是回溯知识查询，不提供提前预警或专家根因标签。数值表保留发布者的公式缓存，未重算、填补缺测或训练模型。源署名、许可与限制见 `sources.json`，Marun保留非商业许可说明。

2026-10-21本地验收：新增1102个节点、2137条关系，552个片段均有512维向量；重复写入没有增加同批节点数。67项测试、12条诊断逻辑题与3道新知识问答规则验收通过。页面完成脚本和接口检查，未做浏览器视觉验收。
