# 部署说明

本文档说明如何部署公开代码和私有运行数据。仓库本身不包含任何真实
指标文件、内网地址或密钥。

## 一、部署架构

```text
浏览器 / API 客户端
          |
          v
GraphRAG API 服务
          |
          +--> 运行时挂载的指标文件
          +--> 可选 Embedding 服务
          +--> 可选 LLM 网关
          +--> 可选 Cross-Encoder 服务
```

前端可以部署到 GitHub Pages。Python API、指标数据和模型服务应部署在
受控服务器或内网中。GitHub Pages 不能保护私有文件和服务密钥。

## 二、环境准备

建议使用 Python 3.11 或更高版本：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
py -3.11 -m pip install -r backend\requirements.txt
```

## 三、准备指标数据

指标数据不是代码，应单独存储。推荐流程：

1. 将已授权的 JSON/TXT 指标文件放在受控目录、对象存储或数据库中；
2. 只授予 API 服务读取权限；
3. 启动服务时通过环境变量指定文件路径；
4. 图谱、三元组和 Embedding 缓存写入运行目录；
5. 不把原始指标、缓存或图谱快照提交到 GitHub。

示例配置：

```powershell
$env:INDICATOR_PATH = "data\approved-indicators.json"
$env:INDICATOR_DATA_DIR = "data"
$env:GRAPHRAG_RUNTIME_DIR = "runtime"
```

`INDICATOR_PATH` 是指标入口文件；`INDICATOR_DATA_DIR` 用于查找别名和
语义配置；`GRAPHRAG_RUNTIME_DIR` 用于保存运行时生成的图谱文件。

## 四、启动 API 服务

```powershell
$env:PORT = "8090"
$env:LLM_BASE_URL = "https://your-llm-gateway.example/v1"
$env:LLM_MODEL = "your-model-name"
$env:LLM_API_KEY = "runtime-secret"

py -3.11 backend\api_server.py
```

接口：

```http
GET /health
```

```http
POST /api/search
Content-Type: application/json

{"query":"自然语言问题","top_k":5,"use_llm":true}
```

返回内容包括匹配指标、分数、匹配原因、所属大类、指标定义和图谱路径。
所有指标必须来自运行时加载的指标库。

## 五、LLM 配置

LLM 只负责查询规划和可选解释，不允许生成指标库之外的名称。建议通过
后端环境变量配置：

```text
LLM_BASE_URL=https://your-llm-gateway.example/v1
LLM_MODEL=your-model-name
LLM_API_KEY=<secret>
```

前端不应直接调用模型服务。正式部署时，浏览器只调用自己的后端代理，
密钥只保存在后端环境或密钥管理系统中。

当 LLM 不可用时，系统仍可使用精确、别名、关键词、Embedding 和图谱
召回完成基础匹配。

## 六、可选 Reranker 服务

项目包含 `backend/reranker_server.py`，用于部署真正的 Cross-Encoder。
该服务只重排第一阶段候选，不创建新指标。

```powershell
$env:RERANK_MODEL = "your-approved-cross-encoder"
$env:RERANK_PORT = "8018"
py -3.11 backend\reranker_server.py
```

API 服务配置：

```powershell
$env:USE_CROSS_ENCODER_RERANK = "true"
$env:CROSS_ENCODER_URL = "http://your-reranker-service:8018/v1/rerank"
$env:CROSS_ENCODER_TIMEOUT = "8"
```

Reranker 必须经过离线评估后才能成为默认排序模块。当前默认关闭，避免
未验证模型降低 Top1 或 Recall@5。

## 七、GitHub Pages 部署

项目包含 `.github/workflows/pages.yml`：

1. 在仓库 Settings 中启用 Pages；
2. Build and deployment 选择 GitHub Actions；
3. 推送 `main` 分支；
4. 等待 Actions 完成；
5. 检查部署产物中不包含私有指标和密钥。

GitHub Pages 只适合静态前端和公开文档。私有指标、API Key、Embedding
服务和 LLM 服务必须放在后端。

## 八、上线前检查

- 扫描 `sk-`、Bearer Token 和密码；
- 扫描内网 IP、内部域名和本机路径；
- 确认 `.env`、缓存、日志、PDF、截图和测试输出未被跟踪；
- 确认指标文件只通过运行时挂载提供；
- 执行 `git diff --cached` 审核暂存内容；
- 若历史提交曾包含密钥，立即撤销并轮换密钥。
