# 设计指标智能匹配助手

这是一个可部署到 GitHub Pages 的静态网页前端，用于围绕“设计指标匹配方案”进行智能对话。

## 功能

- 可编辑“设计指标匹配方案内容”，作为对话知识上下文。
- 左侧展示功能适配、技术可行、成本效率、体验质量、风险控制等匹配维度。
- 支持本地离线兜底回复，无需接口也能演示基本指标匹配流程。
- 支持配置 OpenAI 兼容的 `/v1/chat/completions` 接口。
- 支持保存配置、保留历史、清空对话、导出 Markdown 对话记录。

## 本地预览

直接打开 `index.html` 即可预览。也可以在项目目录运行：

```powershell
python -m http.server 8080
```

然后访问：

```text
http://localhost:8080
```

## 部署到 GitHub Pages

本项目已经包含 `.github/workflows/pages.yml`，推送到 GitHub 后可以用 GitHub Actions 自动发布。

1. 将本目录推送到你的 GitHub 仓库。
2. 打开仓库的 `Settings`。
3. 进入 `Pages`。
4. `Build and deployment` 选择 `GitHub Actions`。
5. 推送 `main` 或 `master` 分支后等待 Actions 完成。

## AI 接口配置建议

公开部署时不要把 API Key 写进代码或提交到 GitHub。推荐方式是：

- 前端填写你自己的后端代理地址。
- 后端代理读取服务器环境变量中的 API Key。
- 前端只向代理发送用户问题和知识上下文。

前端配置项里的 API 地址应兼容 OpenAI Chat Completions 响应格式，例如：

```text
https://your-domain.example/api/chat
```

如果只是本机测试，可以临时在页面里填写 API Key。该值只保存在当前浏览器的 `localStorage`，不会被写入仓库。

## 权限指标集

GitHub Pages 是静态公开托管，不能真正限制仓库内文件访问。因此私有指标集不要放进 `assets/`、`README` 或任何会被发布的静态文件。

页面左侧的“权限指标集”会通过受控后端接口加载指标。接口需要校验访问令牌，并返回以下格式之一：

```json
{
  "metrics": [
    {
      "name": "功能适配",
      "desc": "目标场景、用户需求、业务流程",
      "score": 92
    }
  ]
}
```

也可以直接返回数组：

```json
[
  {
    "name": "功能适配",
    "description": "目标场景、用户需求、业务流程",
    "weight": 0.35
  }
]
```

推荐后端权限策略：

- 指标集接口必须验证 `Authorization: Bearer <token>`。
- Token 由服务端签发和吊销。
- 后端读取私有数据库、私有对象存储或服务器环境变量，不读取 GitHub Pages 静态文件。
- 响应只返回当前用户有权限查看的指标。

## 后续可扩展方向

- 将“设计指标匹配方案”拆成独立 JSON 配置。
- 增加权重滑块，让用户调整指标优先级。
- 接入 GraphRAG 检索后端，返回带来源引用的方案建议。
- 增加登录和项目级历史记录。
