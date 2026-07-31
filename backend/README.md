# GraphRAG API 服务

## 启动

```powershell
cd C:\Users\ASUS\Documents\GraphRAG
py -3.11 -m pip install -r backend\requirements.txt
py -3.11 backend\api_server.py
```

默认监听 `http://127.0.0.1:8090`，同一个地址同时提供网页和 API。

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

打开 `http://127.0.0.1:8090/` 即可使用完整网页。后端负责本地图谱召回、相关性过滤、GraphRAG 路由和 Qwen 重排。浏览器不直接访问 Qwen 内网地址。

环境变量：

```powershell
$env:LLM_BASE_URL = "http://172.20.0.133:8000/v1"
$env:LLM_MODEL = "Qwen3.6-27B-NVFP4"
$env:PORT = "8090"
```

## 运行 100 条接口测试

```powershell
py -3.11 backend\run_api_100_tests.py
```

测试会真实调用 `/api/search` 和 Qwen，结果写入 `outputs/api_qwen_100_test_summary.json` 与 `outputs/api_qwen_100_test_details.csv`。
