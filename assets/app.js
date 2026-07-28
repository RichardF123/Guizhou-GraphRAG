const publicMetricPreview = [
  { name: "功能适配", desc: "目标场景、用户需求、业务流程", score: "--" },
  { name: "技术可行", desc: "数据来源、模型能力、接口集成", score: "--" },
  { name: "成本效率", desc: "开发成本、部署成本、维护成本", score: "--" },
  { name: "体验质量", desc: "响应速度、可解释性、交互负担", score: "--" },
  { name: "风险控制", desc: "隐私、安全、误答和人工复核", score: "--" },
];

const defaultKnowledge = `设计指标匹配方案：
1. 先识别用户的设计目标、使用场景、约束条件和优先级。
2. 从功能适配、技术可行、成本效率、体验质量、风险控制五个维度进行匹配。
3. 对每个维度给出推荐等级、原因、需要补充的数据和下一步动作。
4. 对不确定项给出假设，并提示需要人工确认的关键指标。
5. 输出应包含：指标匹配表、方案建议、风险提示、实施步骤。`;

const state = {
  messages: loadJson("design-chat-history", []),
  metrics: [],
  settings: loadJson("design-chat-settings", {
    apiBaseUrl: "",
    modelName: "gpt-4.1-mini",
    apiKey: "",
    metricEndpoint: "",
    metricAccessToken: "",
  }),
};

const els = {
  metricList: document.querySelector("#metricList"),
  chatStream: document.querySelector("#chatStream"),
  chatForm: document.querySelector("#chatForm"),
  userInput: document.querySelector("#userInput"),
  knowledgeBase: document.querySelector("#knowledgeBase"),
  apiBaseUrl: document.querySelector("#apiBaseUrl"),
  modelName: document.querySelector("#modelName"),
  apiKey: document.querySelector("#apiKey"),
  metricEndpoint: document.querySelector("#metricEndpoint"),
  metricAccessToken: document.querySelector("#metricAccessToken"),
  loadMetrics: document.querySelector("#loadMetrics"),
  saveSettings: document.querySelector("#saveSettings"),
  resetChat: document.querySelector("#resetChat"),
  exportChat: document.querySelector("#exportChat"),
};

function loadJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback;
  } catch {
    return fallback;
  }
}

function saveJson(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

function init() {
  renderMetrics();
  hydrateSettings();
  els.knowledgeBase.value = localStorage.getItem("design-knowledge") || defaultKnowledge;
  renderMessages();

  if (!state.messages.length) {
    addMessage(
      "assistant",
      "你好，我可以根据你的设计指标匹配方案，帮你把需求拆成指标、匹配建议、风险和实施步骤。你可以先描述项目场景、目标用户、已有数据和最重要的评价指标。"
    );
  }

  bindEvents();
  lucide.createIcons();
}

function renderMetrics() {
  const metrics = state.metrics.length ? state.metrics : publicMetricPreview;
  const locked = !state.metrics.length;
  els.metricList.innerHTML = metrics
    .map(
      (item) => `
        <article class="metric-item ${locked ? "locked" : ""}">
          <div>
            <strong>${item.name}</strong>
            <span>${item.desc}</span>
          </div>
          <div class="metric-score">${item.score}</div>
        </article>
      `
    )
    .join("");
  if (locked) {
    els.metricList.insertAdjacentHTML(
      "afterbegin",
      '<p class="locked-note">真实指标集未加载。请通过受控后端接口和访问令牌获取，避免把私有指标公开到 GitHub Pages。</p>'
    );
  }
}

function hydrateSettings() {
  els.apiBaseUrl.value = state.settings.apiBaseUrl;
  els.modelName.value = state.settings.modelName;
  els.apiKey.value = state.settings.apiKey;
  els.metricEndpoint.value = state.settings.metricEndpoint;
  els.metricAccessToken.value = "";
}

function bindEvents() {
  els.chatForm.addEventListener("submit", handleSubmit);
  els.knowledgeBase.addEventListener("input", () => {
    localStorage.setItem("design-knowledge", els.knowledgeBase.value);
  });
  els.loadMetrics.addEventListener("click", loadProtectedMetrics);
  els.saveSettings.addEventListener("click", saveSettings);
  els.resetChat.addEventListener("click", resetChat);
  els.exportChat.addEventListener("click", exportChat);
}

async function handleSubmit(event) {
  event.preventDefault();
  const content = els.userInput.value.trim();
  if (!content) return;

  els.userInput.value = "";
  addMessage("user", content);
  const typingId = addMessage("assistant", "正在匹配设计指标...", true);

  try {
    const reply = await getAssistantReply(content);
    updateMessage(typingId, reply);
  } catch (error) {
    updateMessage(
      typingId,
      `接口调用失败，已切换为本地分析。\n\n${buildLocalReply(content)}\n\n错误信息：${error.message}`
    );
  }
}

async function getAssistantReply(content) {
  const { apiBaseUrl, modelName, apiKey } = state.settings;
  if (!apiBaseUrl || !apiKey) {
    return buildLocalReply(content);
  }

  const response = await fetch(apiBaseUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: modelName || "gpt-4.1-mini",
      temperature: 0.35,
      messages: [
        {
          role: "system",
          content:
            "你是设计指标匹配助手。请基于用户提供的方案内容输出结构化、可执行、谨慎的中文建议。",
        },
        {
          role: "user",
          content: `方案内容：\n${els.knowledgeBase.value}\n\n已授权指标集：\n${formatMetricsForPrompt()}\n\n用户需求：\n${content}`,
        },
      ],
    }),
  });

  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }

  const data = await response.json();
  return data.choices?.[0]?.message?.content?.trim() || "接口返回为空，请检查模型响应格式。";
}

function buildLocalReply(content) {
  const sourceMetrics = state.metrics.length ? state.metrics : publicMetricPreview;
  const lower = content.toLowerCase();
  const detected = sourceMetrics.filter((item) => {
    const text = `${item.name}${item.desc}`.toLowerCase();
    return [...new Set([...content, ...lower])].some((char) => text.includes(char));
  });
  const topMetrics = (detected.length ? detected : sourceMetrics.slice(0, 3)).slice(0, 4);
  const accessNote = state.metrics.length
    ? "已基于授权指标集进行匹配。"
    : "当前未加载授权指标集，以下为公开维度下的演示性建议。";

  return `指标匹配结果：
${accessNote}
${topMetrics.map((item, index) => `${index + 1}. ${item.name}：建议优先评估「${item.desc}」，当前参考匹配度 ${item.score}。`).join("\n")}

方案建议：
围绕你的需求，可以先建立“目标-指标-数据-验证”四层结构。第一步把设计目标写成可衡量问题，第二步为每个指标标注数据来源和权重，第三步用对话系统解释推荐原因，第四步保留人工复核入口。

需要补充的信息：
请继续提供项目类型、目标用户、已有数据、最重要的 3 个指标、必须满足的成本或时间约束。

风险提示：
如果指标权重没有明确来源，系统可能给出看似合理但难以追溯的建议。建议在正式部署前增加引用来源、置信度和人工确认状态。`;
}

async function loadProtectedMetrics() {
  saveSettings(false);
  const endpoint = els.metricEndpoint.value.trim();
  const token = els.metricAccessToken.value.trim();
  if (!endpoint || !token) {
    addMessage("assistant", "请先填写指标集接口和访问令牌。真实指标集不应存放在公开仓库或 GitHub Pages 静态文件里。");
    return;
  }

  els.loadMetrics.textContent = "加载中...";
  try {
    const response = await fetch(endpoint, {
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
      },
    });
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    const data = await response.json();
    const metrics = Array.isArray(data) ? data : data.metrics;
    if (!Array.isArray(metrics)) {
      throw new Error("指标接口需要返回数组，或包含 metrics 数组字段。");
    }
    state.metrics = metrics.map(normalizeMetric).filter(Boolean);
    renderMetrics();
    addMessage("assistant", `已加载 ${state.metrics.length} 个授权指标，可用于后续方案匹配。`);
  } catch (error) {
    addMessage("assistant", `指标集加载失败：${error.message}`);
  } finally {
    els.loadMetrics.innerHTML = '<i data-lucide="key-round" aria-hidden="true"></i>加载指标集';
    lucide.createIcons();
  }
}

function normalizeMetric(item) {
  if (!item || !item.name) return null;
  return {
    name: String(item.name),
    desc: String(item.desc || item.description || "未提供说明"),
    score: item.score ?? item.weight ?? "--",
  };
}

function formatMetricsForPrompt() {
  if (!state.metrics.length) {
    return "未加载。请提示用户先通过授权接口加载指标集，当前只能给出公开维度的演示性建议。";
  }
  return state.metrics
    .map((item, index) => `${index + 1}. ${item.name}：${item.desc}；参考值：${item.score}`)
    .join("\n");
}

function addMessage(role, content, transient = false) {
  const id = crypto.randomUUID();
  const message = { id, role, content, transient, createdAt: new Date().toISOString() };
  state.messages.push(message);
  persistMessages();
  renderMessages();
  return id;
}

function updateMessage(id, content) {
  const message = state.messages.find((item) => item.id === id);
  if (!message) return;
  message.content = content;
  message.transient = false;
  persistMessages();
  renderMessages();
}

function persistMessages() {
  saveJson(
    "design-chat-history",
    state.messages.filter((item) => !item.transient)
  );
}

function renderMessages() {
  els.chatStream.innerHTML = state.messages
    .map(
      (message) => `
        <article class="message ${message.role}">
          <div class="avatar" aria-hidden="true">
            <i data-lucide="${message.role === "user" ? "user" : "sparkles"}"></i>
          </div>
          <div class="bubble ${message.transient ? "typing" : ""}">${escapeHtml(message.content)}</div>
        </article>
      `
    )
    .join("");
  els.chatStream.scrollTop = els.chatStream.scrollHeight;
  lucide.createIcons();
}

function saveSettings(showFeedback = true) {
  state.settings = {
    apiBaseUrl: els.apiBaseUrl.value.trim(),
    modelName: els.modelName.value.trim() || "gpt-4.1-mini",
    apiKey: els.apiKey.value.trim(),
    metricEndpoint: els.metricEndpoint.value.trim(),
    metricAccessToken: "",
  };
  saveJson("design-chat-settings", state.settings);
  if (!showFeedback) return;
  els.saveSettings.textContent = "已保存";
  setTimeout(() => {
    els.saveSettings.innerHTML = '<i data-lucide="save" aria-hidden="true"></i>保存配置';
    lucide.createIcons();
  }, 1200);
}

function resetChat() {
  state.messages = [];
  persistMessages();
  renderMessages();
  addMessage("assistant", "对话已清空。你可以输入新的设计场景，我会重新进行指标匹配。");
}

function exportChat() {
  const lines = state.messages
    .map((item) => `## ${item.role === "user" ? "用户" : "助手"}\n${item.content}`)
    .join("\n\n");
  const blob = new Blob([lines], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `design-chat-${new Date().toISOString().slice(0, 10)}.md`;
  link.click();
  URL.revokeObjectURL(url);
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

document.addEventListener("DOMContentLoaded", init);
