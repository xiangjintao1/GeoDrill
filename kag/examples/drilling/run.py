# Copyright 2026 向金涛
# Affiliation: 吉林大学
"""钻探模块入口。inspect 可离线运行，其余命令复用 KAG 组件。"""

import argparse
import asyncio
import importlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

PROJECT_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = PROJECT_DIR / "schema" / "Drilling.schema"
ENV_FIELDS = {
    "project": {"host_addr": "HOST", "id": "PROJECT_ID"},
    "openie_llm": {"base_url": "LLM_URL", "api_key": "LLM_KEY", "model": "LLM_MODEL"},
    "vectorize_model": {
        "base_url": "EMBEDDING_URL", "api_key": "EMBEDDING_KEY",
        "model": "EMBEDDING_MODEL", "vector_dimensions": "EMBEDDING_DIMENSIONS",
    },
}


def load_config(path):
    import yaml

    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    for section, fields in ENV_FIELDS.items():
        for field, suffix in fields.items():
            value = os.getenv(f"DRILLING_{suffix}")
            if value:
                config[section][field] = value
    # checkpoint 按项目隔离，避免复用生物知识库的抽取结果。
    config["project"]["checkpoint_path"] = str(PROJECT_DIR / "ckpt")
    return config


def validate_config(config):
    errors = []
    for section, fields in ENV_FIELDS.items():
        for field in fields:
            if section == "openie_llm" and config[section].get("type") == "chatgpt_oauth" and field in {"api_key", "base_url"}:
                continue
            value = config.get(section, {}).get(field)
            if value is None or not str(value).strip() or str(value).startswith("YOUR_"):
                errors.append(f"请配置 {section}.{field}")
            elif field in {"id", "vector_dimensions"}:
                if not str(value).isdigit() or int(value) <= 0:
                    errors.append(f"{section}.{field} 必须是正整数")
                else:
                    config[section][field] = int(value)
            elif field in {"host_addr", "base_url"}:
                url = urlparse(str(value))
                if url.scheme not in {"http", "https"} or not url.netloc:
                    errors.append(f"{section}.{field} 必须是 HTTP(S) 地址")
    if config["project"].get("namespace") != "Drilling":
        errors.append("project.namespace 必须与 Drilling.schema 的 Drilling 一致")
    if errors:
        raise ValueError("\n".join(errors))


def corpus_files(directory):
    files = sorted(directory.rglob("*.md")) if directory.is_dir() else []
    if not files:
        raise ValueError(f"没有找到 Markdown 语料：{directory}")
    for path in files:
        if not path.read_text(encoding="utf-8").strip():
            raise ValueError(f"语料为空：{path.name}")
    return files


def init_runtime(config):
    # Kag 在 import 时自动初始化；先清除可能指向旧项目的环境变量。
    for name in ("KAG_PROJECT_ID", "KAG_PROJECT_HOST_ADDR", "KAG_PROJECT_NAMESPACE"):
        os.environ.pop(name, None)
    sys.path.insert(0, str(PROJECT_DIR.parents[2]))
    os.chdir(PROJECT_DIR)
    from kag.common.conf import KAG_CONFIG

    KAG_CONFIG.config = config
    KAG_CONFIG.global_config.initialize(**config["project"])
    KAG_CONFIG.init_log_config(config)
    os.environ["KAG_PROJECT_ID"] = str(config["project"]["id"])
    os.environ["KAG_PROJECT_HOST_ADDR"] = config["project"]["host_addr"]
    os.environ["KAG_PROJECT_NAMESPACE"] = config["project"]["namespace"]
    importlib.import_module("kag.examples.drilling.prompts")
    importlib.import_module("kag.examples.drilling.query_pipeline")
    if config["openie_llm"].get("type") == "chatgpt_oauth":
        importlib.import_module("kag.examples.drilling.chatgpt_client")


def commit_schema(config):
    from kag.indexer import KAGIndexManager
    from knext.schema.marklang.schema_ml import SPGSchemaMarkLang

    project = config["project"]
    connection = {"host_addr": project["host_addr"], "project_id": project["id"]}
    schema = SPGSchemaMarkLang(str(SCHEMA_PATH), **connection)
    # 同上游 schema commit，补齐 Chunk、Doc 等检索索引所需类型。
    for name in KAGIndexManager.list_available():
        manager = KAGIndexManager.from_config({
            "type": name, "llm_config": None, "vectorize_model_config": None,
        })
        if manager.schema:
            index_schema = SPGSchemaMarkLang(
                "", script_data_str="namespace Drilling\n" + manager.schema, **connection,
            )
            schema.types.update(index_schema.types)
    schema.sync_schema()
    print("Schema 已同步；请确认服务端向量索引维度与 embedding 配置一致。")


async def build(config, files):
    from kag.interface import KAGBuilderChain
    from kag.common.checkpointer import CheckpointerManager

    chain = KAGBuilderChain.from_config(config["kag_builder_pipeline"]["chain"])
    try:
        for path in files:
            result = await chain.ainvoke(str(path), max_concurrency=2)
            if not result:
                raise ValueError(f"{path.name} 没有返回构建结果，请检查日志与 checkpoint")
            print(f"已处理 {path.name}，返回 {len(result)} 项；请在服务端核对图谱和索引。")
    finally:
        CheckpointerManager.close()


async def ask(config, question, output=None, emit=True):
    from kag.interface import SolverPipelineABC
    from kag.solver.reporter.trace_log_reporter import TraceLogReporter

    reporter = TraceLogReporter()
    pipeline = SolverPipelineABC.from_config(config["kag_solver_pipeline"])
    answer = await pipeline.ainvoke(question, reporter=reporter)
    trace, status = reporter.generate_report_data()
    result = {"question": question, "answer": answer, "status": status, "trace": trace.to_dict()}
    if emit:
        print(answer)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if emit:
            print(f"答案和检索过程已保存至 {output}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_DIR / "kag_config.yaml")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="离线检查语料，不调用模型或写入知识库")
    inspect.add_argument("--data", type=Path, default=PROJECT_DIR / "examples" / "corpus")
    commands.add_parser("check", help="检查本地配置，不验证服务连通性")
    commands.add_parser("schema", help="向目标 OpenSPG 项目同步 Schema")
    builder = commands.add_parser("build", help="抽取、向量化并写入目标知识库")
    builder.add_argument("--data", type=Path, default=PROJECT_DIR / "data")
    builder.add_argument("--text-only", action="store_true", help="仅索引来源文本，复用上游片段抽取器，省去实体抽取调用")
    solver = commands.add_parser("ask", help="检索知识库并回答一个问题")
    solver.add_argument("question")
    solver.add_argument("--output", type=Path, help="保存包含引用和检索过程的 JSON")
    args = parser.parse_args()
    try:
        files = corpus_files(args.data.resolve()) if args.command in {"inspect", "build"} else []
        if args.command == "inspect":
            for path in files:
                print(f"{path.name}: {len(path.read_text(encoding='utf-8'))} 字符")
            print(f"共 {len(files)} 份语料；仅检查文件，尚未抽取或建库。")
            return 0
        config = load_config(args.config.resolve())
        if args.command == "build" and args.text_only:
            config["kag_builder_pipeline"]["chain"]["extractor"] = {"type": "naive_rag_extractor"}
        validate_config(config)
        if args.command == "check":
            print("配置格式检查通过；尚未验证依赖、服务、Schema 和索引。")
            return 0
        output = args.output.resolve() if args.command == "ask" and args.output else None
        init_runtime(config)
        if args.command == "schema":
            commit_schema(config)
        elif args.command == "build":
            asyncio.run(build(config, files))
        else:
            asyncio.run(ask(config, args.question, output))
        return 0
    except (ValueError, OSError, ImportError) as error:
        print(f"执行失败：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
