# 本地服务

2026-10-17 已启动四个容器，创建钻探项目 `Drilling`（ID 1），同步 Schema 并导入两份教学示例和8份公开资料摘要。
Python 钻探流程使用 ChatGPT 官方登录授权；中文向量模型为本地 BGE-small-zh-v1.5（512 维）。
后续已补入基础知识与手册正文，目前共248个可检索文本片段；材料覆盖与证据边界见 [资料清单](../../kag/examples/drilling/corpus/README.md)。

需要先在 BIOS 开启虚拟化、启用 WSL 2 并重启，然后打开 Docker Desktop，等待引擎就绪。
本配置基于 OpenSPG v0.8 官方编排，固定镜像摘要、保留数据库卷，仅监听本机端口。

仓库根目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/local/start.ps1
```

钻探问答工作台：<http://127.0.0.1:8090>，包含问答、资料目录与评测报告。
OpenSPG 管理页面：<http://127.0.0.1:8887>；初始账户 `openspg`，密码 `openspg@kag`。
现有本机配置保存在 `kag/examples/drilling/kag_config.local.yaml`；登录凭据独立加密保存。
OpenSPG 页面用于管理知识库；工作台通过 Python 钻探入口使用 ChatGPT 授权，不依赖管理页面自带的模型配置。

```powershell
.venv\Scripts\python.exe kag/examples/drilling/run.py --config kag/examples/drilling/kag_config.local.yaml ask '绿色钻探示范项目采用了什么钻头？'
```

启动脚本也会启动本地向量服务 `http://127.0.0.1:9230`，模型缓存位于 `D:/GeoDrill-local/models`，日志位于 `D:/GeoDrill-local/logs`。OpenSPG 容器通过 `host.docker.internal:9230` 访问同一服务。

```powershell
# 查看状态、日志；停止时保留数据
docker compose -f deploy/local/compose.yaml ps
docker compose -f deploy/local/compose.yaml logs --tail 80 server
docker compose -f deploy/local/compose.yaml down
```

Python 环境：`.venv/Scripts/python.exe`（3.10）。重新安装依赖时：
`uv pip install --python .venv/Scripts/python.exe -c deploy/local/constraints.txt -e .`。
此处约束避免原项目 MCP 1.6 与新版 Pydantic 的导入冲突。
另外安装本地接入依赖：

```powershell
uv pip install --python .venv/Scripts/python.exe -c deploy/local/constraints.txt -r deploy/local/requirements-chatgpt.txt -r deploy/local/requirements-embedding.txt
```
