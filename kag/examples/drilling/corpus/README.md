# 钻探知识库资料

## 基础手册扩充

2026-10-17新增：[USGS完整钻探、取心与采样手册](https://pubs.usgs.gov/twri/twri2-f1/pdf/TWRI_2-F1.pdf)，1989，正文97页、PDF文件106页。原始PDF缓存位于 `D:/GeoDrill-local/materials/usgs/`。已选取其中28页相关正文，整理为204个带页码的英文检索片段（`reference/`），另有28个中文知识条目（`foundation/usgs-*.md`）。没有把全部106页计入知识库。

中文内容覆盖取心与全面钻进、绳索取心、内外管与打捞器、钻杆与钻铤、套管、泥浆黏度与密度、泥皮、含砂量、钻压与转速、软硬互层、孔壁稳定、堵塞漏失、岩心标识、样品扰动和保存。历史手册用于原理学习，不作为现行中国规程；英文正文可能保留OCR错误，图表未自动转录。不同来源的水口名称需要结合结构理解。

另有4条国内标准目录信息：DZ/T 0227-2010、GB/T 16950-2014、DZ/T 0277-2015、DZ/T 0278-2015。官方平台在核验时均列为推荐性、现行；链接见 `foundation/standard-*.md`。**尚未取得并核对标准全文，不能依据目录回答条款、尺寸或公差。**

手册正文和中文条目仅进行文本向量化，复用上游片段抽取器，省去逐段大模型抽取；原案例图谱保留。问答仍调用授权模型。

```powershell
.venv\Scripts\python.exe kag/examples/drilling/run.py --config kag/examples/drilling/kag_config.local.yaml build --text-only --data kag/examples/drilling/corpus/foundation
.venv\Scripts\python.exe kag/examples/drilling/run.py --config kag/examples/drilling/kag_config.local.yaml build --text-only --data kag/examples/drilling/corpus/reference
```

新增出处、页码与校验值见 `foundation-sources.json`；验收问题见 `foundation-questions.json`。仍需补充国内规范全文、完整钻具装配检修手册、现代设备参数表、真实项目记录及更系统的取心质量评价资料。

本批已核对全部236个新增条目的入库来源；连同首批案例及原示例，目前共248个文本片段。已实测绳索取心原理、黏度与密度区别，以及标准全文缺失时的证据不足回答，引用编号均可对应召回片段。建库日志未出现大模型调用。详见 [扩充验收记录](foundation-verification.json)；问题集中的其余问题尚未逐项实测。

## 首批案例资料

核验日期：2026-10-17。`public/` 中为根据原始页面整理的中文摘要，共8份；保留了型号、单位、来源及适用条件。它们用于学习和问答验证，不是原文全文、完整教材或施工规程。厂家建议保留厂家归属，工程效果保留案例范围；未核验现行技术标准。

| 文件 | 内容 | 来源性质 |
|---|---|---|
| [01](public/01-complex-formations.md) | H规格强制取心、P/H跨径钻具、低摩阻岩心管 | 地调局工程案例 |
| [02](public/02-deep-wireline.md) | 深孔内管到位、堵心报警与打捞机构 | 地调局成果报道 |
| [03](public/03-hydraulic-coring.md) | 泥浆压力驱动的回转式绳索取心系统 | 地调局成果报道 |
| [04](public/04-pc1336m-bj.md) | PC1336M-BJ复合片取心钻头 | 地调局工程案例 |
| [05](public/05-nr826m.md) | NR826M全面钻头、直径和井内效果 | 地调局工程案例 |
| [06](public/06-viking-matrices.md) | VIKING胎体与地层条件 | Epiroc产品页 |
| [07](public/07-surface-set-profiles.md) | 表镶钻头冠部形状、SPC含义 | Epiroc产品页 |
| [08](public/08-high-temperature-tools.md) | 高温涡轮与孕镶钻头组合 | 地调局技术报道 |

原始链接和日期见各文件；各文件只有一个标题，使来源与正文保留在同一检索片段。只将 `public/` 作为建库输入，避免把本清单写入知识库。

```powershell
.venv\Scripts\python.exe kag/examples/drilling/run.py --config kag/examples/drilling/kag_config.local.yaml build --data kag/examples/drilling/corpus/public
```

验收问题见 `questions.json`，实际回答保存在模块的 `results/` 中。

首批验证记录：8份摘要写入后，连同原有示例共12个文本片段（不含本次手册扩充）。34个向量索引均为512维且已上线。已实测“钻头型号及缺失参数”和“SPC含义及STEP适用限制”两组问答；其余问题未逐项运行。首批结果见 [verification.json](verification.json)。
