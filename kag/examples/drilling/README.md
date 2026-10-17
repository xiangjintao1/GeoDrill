# GeoDrill · 钻井异常辅助诊断与知识工作台

范围：**钻进工艺与取心、钻头与钻具**。已连接本地 OpenSPG、BGE 中文向量模型和对话模型，建有 248 个知识片段；其中 244 条公开资料可在目录浏览，其余为最初的示例片段。

## 工作台与评测

新增[钻井异常分析原型](diagnosis/README.md)：8个已发表案例摘要、5条机制检查规则，支持未知观测、不符线索和追问；通过KAG业务执行器读取OpenSPG诊断图谱，不修改框架源码。现有资料问答保留。案例不是独立核验的根因金标准。

已有本地环境可直接启动，访问 **http://127.0.0.1:8090**：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/local/start.ps1
```

- 知识问答：混合/向量检索切换、引用定位、证据原文、来源链接和检索过程。
- 资料目录：按标题或正文搜索，区分案例、手册、中文条目与标准目录。
- 质量评测：同一套题对照两种检索方式，展示来源召回、事实规则、引用编号及耗时。
- 性能诊断：页面实时显示处理进度和逐步生成的回答，完成后展示阶段耗时、模型次数；见[优化记录](../../../docs/性能优化.md)。

运行 8 题、两种模式共 16 次真实问答（使用已配置的模型服务）：

```powershell
.venv\Scripts\python.exe kag/examples/drilling/evaluate.py
```

报告保存到 `results/evaluation/latest.json`，刷新页面即可查看。`--limit 2` 可先检查连通性。
`benchmark.json` 可增补题目；事实规则仅做关键词检查，引用校验仅核对编号，均不能代替人工语义评审。当前小样本不能用于宣称准确率或优化提升。

2026-10-17 首轮结果：混合检索规则验收 8/8，平均 44.23 秒；纯向量检索 7/8，平均 38.47 秒，两组均无调用错误。纯向量在绳索取心原理题未召回证据；这仅反映本轮 8 题，不构成稳定优势的证明。完整记录见 `results/evaluation/latest.json`。

## 文件

- `schema/Drilling.schema`：8类原领域实体及4类诊断知识实体。
- `prompts.py`：仅从原文抽取、实体别名统一、引用回答。
- `kag_config.yaml`：构建与问答流水线；默认最多并行处理 2 个构建任务。
- `run.py`：检查语料、检查配置、同步 Schema、建库、问答。
- `service.py` / `web.py` / `workbench.html`：业务服务、本地 HTTP 接口与工作台。
- `evaluate.py` / `benchmark.json`：对照评测与验收规则。
- `examples/`：2 份带来源的案例摘要和 4 个手工验收问题。
- `corpus/`：[案例摘要、基础知识条目、手册正文和来源清单](corpus/README.md)，覆盖取心原理、工艺、钻具及质量控制。

## 运行

先在仓库根目录执行以下命令，只需 Python，不会调用 API：

```powershell
python kag/examples/drilling/run.py inspect
```

接入服务时使用独立的 Python 3.10/3.11 环境，在仓库根目录执行
`pip install -c deploy/local/constraints.txt -e .`（兼容原项目的 MCP 依赖）。
在 OpenSPG 创建独立项目，命名空间设为 `Drilling`，然后设置连接信息：

```powershell
$env:DRILLING_HOST = "http://127.0.0.1:8887"
$env:DRILLING_PROJECT_ID = "你的项目ID"
$env:DRILLING_LLM_URL = "你的OpenAI兼容接口地址"
$env:DRILLING_LLM_KEY = "你的密钥"
$env:DRILLING_LLM_MODEL = "你的对话模型名称"
$env:DRILLING_EMBEDDING_URL = "你的向量模型接口地址"
$env:DRILLING_EMBEDDING_KEY = "你的向量模型密钥"
$env:DRILLING_EMBEDDING_MODEL = "你的向量模型名称"
$env:DRILLING_EMBEDDING_DIMENSIONS = "你的模型输出维度"

python kag/examples/drilling/run.py check
python kag/examples/drilling/run.py schema
python kag/examples/drilling/run.py build --data kag/examples/drilling/examples/corpus
python kag/examples/drilling/run.py ask "绿色钻探示范项目采用了什么钻头？" --output kag/examples/drilling/results/answer.json
```

`check` 仅检查配置格式。`schema` 会修改目标项目结构；`build` 会调用模型并写入知识库。
服务端索引维度须与向量模型输出一致；模型或语料变化后，应在独立项目重建并使用新的 checkpoint。
私有语料放在本模块的 `data/`，运行 `build` 即可；不要把说明文档放入语料目录。

## 看懂流程

建库：Markdown → reader → splitter → extractor → vectorizer → post_processor → writer。
问答：问题 → planner → 图谱/文本检索 → generator → 答案与引用。

代码采用上游异步构建接口，逐文件处理；2 是片段处理并发上限，不代表模型请求总数。
Schema 决定知识结构，Prompt 决定抽取要求，具体事实由语料提供。
当前使用开放关系抽取：Schema 提供类别，Prompt 约束谓词，不保证模型完全遵守；需人工检查抽取结果。
未召回原文时直接返回证据不足；有原文时仍需用 `examples/questions.json` 检查回答是否忠实。
验收时检查答案、来源片段、引用是否匹配，以及缺失的型号/数值是否被编造。
## 使用 ChatGPT Plus / Pro 账号

钻探命令行支持官方 OAuth 套餐授权（账号实际权限以授权页面为准）：

```powershell
uv pip install --python .venv\Scripts\python.exe -r deploy/local/requirements-chatgpt.txt
.venv\Scripts\python.exe kag/examples/drilling/chatgpt_auth.py login
.venv\Scripts\python.exe kag/examples/drilling/chatgpt_auth.py models
```

在本地配置的 `openie_llm` 中设置 `type: chatgpt_oauth`，`model` 使用登录后返回的模型 slug；保持 YAML 别名，让建库、规划和回答共用它。此类型不需要 `api_key`、`base_url` 或 `temperature`。授权凭据通过 Windows DPAPI 加密，存放于 `%LOCALAPPDATA%/GeoDrill/chatgpt`，不写入项目配置。运行 `chatgpt_auth.py logout` 可清除本地凭据。

这只适配 Python 钻探流程，OpenSPG 管理页面仍是原来的服务。向量模型需要单独配置，登录成功也不代表知识库已经建立。

依据：[官方登录流程](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)、[Responses 调用约束](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)。

## 来源

底层使用 OpenSPG KAG；版权与许可信息集中见 [NOTICE](../../../NOTICE) 和 [LICENSE](../../../LICENSE)。
