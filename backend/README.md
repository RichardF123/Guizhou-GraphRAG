# GraphRAG API 服务

## 启动

```powershell
cd C:\Users\ASUS\Documents\GraphRAG
py -3.11 -m pip install -r backend\requirements.txt
py -3.11 backend\api_server.py
```

默认监听 `http://127.0.0.1:8090`。

## 接口

### 健康检查

```http
GET /health
```

### 指标匹配

```http
POST /api/search
Content-Type: application/json

{"query":"村里没人照顾的老人有多少","top_k":5,"use_llm":true}
```

后端负责本地图谱召回、相关性过滤、GraphRAG 路由和 Qwen 重排。浏览器不直接访问 Qwen 内网地址。

环境变量：

```powershell
$env:LLM_BASE_URL = "http://172.20.0.133:8000/v1"
$env:LLM_MODEL = "Qwen3.6-27B-NVFP4"
$env:PORT = "8090"
```
