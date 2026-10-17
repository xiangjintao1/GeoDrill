# 钻井异常案例与机制检查

优先范围：卡钻、环空堵塞、井漏。`cases.json` 为8个已发表事件的事实摘要，`knowledge.json` 为来源可追溯的6条机制检查规则。
现成资料仍需核对：作者“可能原因”、厂家案例、确认的事件记录分别保存；没有直接取得可作为独立根因金标准的完整标注数据集。

| 资料 | 可用内容 | 使用限制 |
| --- | --- | --- |
| [孔雀亭B2H井](https://html.rhhz.net/hysy/html/20170314.htm) | 完整经过、地层与钻井液分析、原因与结果 | 以该井为范围，非通用操作规程 |
| [湘南3000 m科学深钻](https://tkgc.ijournals.cn/tkgc/article/html/20220223?st=search) | 同井两次卡钻的经过和原因分析 | 同井事件不得拆到训练、测试两边 |
| [渤海油田A井](https://journal.lnpu.edu.cn/syhg/CN/Y2018/V31/I02/70) | 卡钻、断裂、打捞、侧钻及分析 | 匿名井，原始时序未公开 |
| [Menengai复盘报告](https://gogn.orkustofnun.is/unu-gtp-report/UNU-GTP-2014-27.pdf) | 表6事件记录、表7候选原因、参数趋势图 | 已核对PDF第19、20、22页；存在深度/时刻/返出记载差异，不能自动修正 |
| [NOV德国地热井案例](https://assets.nov.com/NCP4N68N/at/kk3xrntg3729jf4t6nfqxk3q/DBA_Stuck_Pipe_Managed_with_Real_Time_DBA_Alerts_Case_Study.pdf) | 事件时间线、预警与结果 | 厂家报告，不作为独立根因金标准 |
| [Volve预处理TSPP](https://github.com/promiseeee/Time-series-stuck-pipe-prediction) | 4个基础CSV，实测52905行、时间戳和10个钻井变量 | 无独立标签列；列名不完全一致；须追溯[Volve许可](https://www.equinor.com/energy/volve-data-sharing)，仓库未见LICENSE，不在本仓库再分发原文件 |

PDF和CSV仅下载至本机 `D:\GeoDrill-local\materials\diagnosis`，本仓库保留自行整理的事实摘要、出处与限制，不镜像原始出版物。
`materials.json` 记录9个实际下载文件的来源、大小与SHA-256；TSPP下载地址固定到已验证的Git提交。
`observations` 仅用于诊断输入，`author_analysis` 留作人工对照，避免答案泄漏。小样本、同井和同源案例不支持宣称真实诊断准确率。

工作台“异常分析”可选择案例填入已知观测。`GET /api/diagnosis/schema` 返回字段与案例，`POST /api/diagnose` 接收 `{"observations":{"stuck":"yes"}}`；值仅允许 `yes/no/unknown`，作者原因分析不能混入请求。

构图命令（本模块共5类诊断实体，29个节点、46条边）：

```powershell
.venv\Scripts\python.exe kag/examples/drilling/diagnosis_graph.py
```

KAG注册接口编排“图谱读取→条件/依赖检查与案例对照”任务；后两项并行。新机制链为“环空堵塞线索 + 钻柱运动受限 → 环空堵塞相关卡钻的间接线索”，不是确定诊断，不反向补写现场观测。
前置未知或不符会传递至下游。追问按影响的规则数量排序，这不是故障概率或信息增益估计。
8个案例的事发观测存入OpenSPG。对照只使用已知观测，展示一致、不符和原案例未记载项；原作者原因分析不入诊断图谱、不参与排序。
图谱缺失、版本或来源不匹配会报错，不回退成本地规则冒充图谱查询。框架源码保持不动。
本版是KAG任务编排加业务规则原型，不调用大模型生成诊断；尚未实现自然语言观测抽取、时序异常检测或专家验证的根因推断，也不能据此宣称优于RAG。

逻辑回归验收：`.venv\Scripts\python.exe kag/examples/drilling/evaluate_diagnosis.py`。12道人工设计的逻辑题经真实HTTP接口验收，报告保存于`results/diagnosis/latest.json`；它们不是新增的12个真实案例。单元与集成测试共44项通过，页面仅完成脚本语法和接口检查，未做浏览器视觉验收。
