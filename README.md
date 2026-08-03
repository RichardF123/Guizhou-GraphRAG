# 指标知识图谱 GraphRAG

本项目用于将用户的自然语言问题匹配到已授权的结构化指标。系统采用
“指标知识图谱 + 混合召回 + 规则排序 + 可选大模型规划”的 GraphRAG 架构。

## 文档导航

| 文档 | 内容 |
|---|---|
| [技术方案](TECHNICAL_DESIGN.md) | 数据建模、图谱构建、召回、排序和评估原理 |
| [部署说明](PUBLIC_DEPLOYMENT.md) | 环境准备、数据挂载、模型配置和上线步骤 |
| [后端说明](backend/README.md) | API 服务和 Reranker 服务启动方式 |
| [Agent 设计](AGENT_DESIGN.md) | 前端交互和产品设计说明 |

## 系统能力

- 从指标名称、定义、类别、别名和统计口径构建指标图谱；
- 支持精确匹配、别名匹配、关键词匹配、Embedding 召回和图谱扩展；
- 使用可选 LLM 抽取用户问题中的对象、属性、条件和查询意图；
- 对“马铃薯/土豆”等同义词进行互召回，同时保证用户原词优先；
- 对“马”等短词执行精确匹配保护，避免错误的字符串包含召回；
- 返回指标定义、所属大类、匹配原因和图谱路径；
- 提供可选的 Cross-Encoder 二阶段重排接口。

## 快速启动

项目不包含私有指标文件和模型服务。先准备一份经过授权的指标文件，
再按部署文档配置运行时路径。

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
py -3.11 -m pip install -r backend\requirements.txt

$env:INDICATOR_PATH = "data\approved-indicators.json"
$env:INDICATOR_DATA_DIR = "data"
$env:GRAPHRAG_RUNTIME_DIR = "runtime"
$env:PORT = "8090"

py -3.11 backend\api_server.py
```

浏览器访问：`http://127.0.0.1:8090/`

接口地址：`POST /api/search`

## 安全边界

本仓库只保存公开代码和部署文档，不保存：

- API Key、Token 或密码；
- 内网模型地址；
- 私有指标原始文件；
- Embedding 缓存和图谱运行产物；
- 测试导出、截图、PDF 和本机路径。

私有指标必须在部署时挂载，模型地址和密钥必须通过环境变量或密钥管理
系统注入，不能写入前端、代码和提交记录。

## 当前评估基线

在当前 100 条测试集上，默认主链路结果为：

```text
Top1 命中率：89.58%
Recall@5：100%
MRR@5：94.44%
类别召回率：96.15%
```

Cross-Encoder 目前是可选实验能力，只有在真实模型服务通过同口径测试后
才建议开启。
