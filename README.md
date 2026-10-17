# GeoDrill · 钻探知识工作台

作者：向金涛 · 组织：吉林大学

面向**钻进工艺与取心、钻头与钻具**的知识问答项目。支持资料检索、证据溯源与检索效果对照。

## 功能

- 知识问答：混合检索与纯向量检索切换，显示答案、引用原文和检索过程。
- 资料目录：搜索浏览案例、产品摘要、手册正文和中文知识条目。
- 质量评测：固定题集比较来源命中、事实规则、引用编号和耗时。
- 领域建模：8 类钻探实体及关系；本地已导入 248 个知识片段。

## 本地启动

已配置环境下，在仓库根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/local/start.ps1
```

- 工作台：http://127.0.0.1:8090
- 知识库管理：http://127.0.0.1:8887

首次环境搭建见[本地部署](deploy/local/README.md)，模型配置和命令行用法见[模块说明](kag/examples/drilling/README.md)。

## 验证

```powershell
.venv\Scripts\python.exe -m unittest discover -s kag/examples/drilling/tests -v
.venv\Scripts\python.exe kag/examples/drilling/evaluate.py
```

评测调用已配置的在线模型。首轮 8 题中，混合检索规则验收 8/8，纯向量 7/8；小样本规则检查不等于真实准确率。报告位于 `kag/examples/drilling/results/evaluation/latest.json`。

## 目录

| 路径 | 用途 |
| --- | --- |
| `kag/examples/drilling/` | 钻探业务、工作台、语料、评测与测试 |
| `deploy/local/` | 本地容器、向量服务和启动脚本 |
| `docs/` | 开发流程与代码学习文档 |
| `kag/`、`knext/` | 知识构建、检索推理及服务客户端 |

资料范围与证据限制见[资料清单](kag/examples/drilling/corpus/README.md)。项目使用 OpenSPG KAG、Neo4j 和本地 BGE 向量模型；版权与许可信息见 [NOTICE](NOTICE) 和 [LICENSE](LICENSE)。
