const defaultKnowledge = `匹配策略：
1. 先理解用户问题中的主题、地区、对象、时间和分析目的。
2. 优先在贵州统计局指标集中匹配指标名称、别名、分类、口径说明和来源。
3. 对命中的指标给出推荐理由，并区分主指标、辅助指标和需要确认的指标。
4. 如果现有指标覆盖不足，给出联网检索关键词和官方来源优先级。
5. 输出包括：问题理解、推荐指标、缺口指标、检索建议、简短统计分析报告。`;

const stopWords = [
  "我想", "帮我", "查询", "了解", "看看", "看下", "分析", "情况", "指标",
  "哪些", "哪个", "有什么", "有没有", "是多少", "有多少", "相关", "贵州",
  "村里的", "村里", "村庄", "本村", "包括哪些", "相关指标", "可以", "需要", "一下", "方面", "的"
];

const broadMetricNames = new Set([
  "人数", "数量", "个数", "户数", "面积", "情况", "基本情况", "人口情况",
  "利用情况", "收益总额", "经营收入", "从业人员", "从业人员数"
]);

const globalWords = ["哪些", "有哪些", "包括", "包含", "方面", "分类", "类别", "相关指标", "指标有"];
const localWords = ["是否", "有没有", "有无", "能否", "做了没有", "我想看", "查询", "多少", "有多少", "是多少"];
const compareWords = ["比较", "对比", "区别", "差异", "分别"];

const webSourceHints = [
  "贵州省统计局",
  "贵州统计年鉴",
  "贵州省国民经济和社会发展统计公报",
  "国家统计局",
  "贵州省人民政府 数据"
];

const state = {
  messages: loadJson("design-chat-history", []),
  metrics: [],
  metricPayload: null,
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
  metricSummary: document.querySelector("#metricSummary"),
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

async function init() {
  hydrateSettings();
  els.knowledgeBase.value = localStorage.getItem("design-knowledge") || defaultKnowledge;
  bindEvents();
  await loadBuiltInMetrics();
  renderMessages();

  if (!state.messages.length) {
    addMessage(
      "assistant",
      "你好，我已经载入贵州统计指标集。你可以直接用自然语言提问，比如“村里养老相关怎么看”“产业发展有哪些指标”“农村水利设施包括哪些”。我会先匹配现有指标，覆盖不足时再给出联网补充检索和简短报告。"
    );
  }

  refreshIcons();
}

async function loadBuiltInMetrics() {
  try {
    const payload = window.GZ_INDICATOR_DATA || await fetchMetricPayload("assets/indicators.json");
    applyMetricPayload(payload, "内置指标集");
  } catch (error) {
    state.metrics = [];
    els.metricSummary.textContent = `内置指标集加载失败：${error.message}`;
    renderMetrics();
  }
}

async function fetchMetricPayload(url) {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function applyMetricPayload(payload, label) {
  const metrics = Array.isArray(payload) ? payload : payload.metrics;
  if (!Array.isArray(metrics)) {
    throw new Error("指标数据需要是数组，或包含 metrics 数组字段。");
  }
  state.metricPayload = payload;
  state.metrics = metrics.map(normalizeMetric).filter(Boolean);
  const categories = new Set(state.metrics.map((item) => item.category).filter(Boolean));
  els.metricSummary.textContent = `${label}已加载：${state.metrics.length} 个指标，覆盖 ${categories.size} 个分类。`;
  renderMetrics();
}

function renderMetrics() {
  if (!state.metrics.length) {
    els.metricList.innerHTML = '<p class="locked-note">指标集未加载。请检查 assets/indicators.js，或通过受控接口重新加载。</p>';
    return;
  }

  const categoryStats = [...groupByCategory().entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8);

  els.metricList.innerHTML = categoryStats
    .map(
      ([category, count]) => `
        <article class="metric-item">
          <div>
            <strong>${escapeHtml(category)}</strong>
            <span>${count} 个指标</span>
          </div>
          <div class="metric-score">${count}</div>
        </article>
      `
    )
    .join("");
}

function groupByCategory() {
  const map = new Map();
  for (const metric of state.metrics) {
    const category = metric.category || "未分类";
    map.set(category, (map.get(category) || 0) + 1);
  }
  return map;
}

function metricsByCategory() {
  const map = new Map();
  for (const metric of state.metrics) {
    const category = metric.category || "未分类";
    if (!map.has(category)) map.set(category, []);
    map.get(category).push(metric);
  }
  return map;
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
  const typingId = addMessage("assistant", "正在从贵州统计指标集中匹配...", true);

  try {
    const localResult = analyzeQuestion(content);
    const reply = await getAssistantReply(content, localResult);
    updateMessage(typingId, reply);
  } catch (error) {
    updateMessage(typingId, `处理失败：${error.message}`);
  }
}

async function getAssistantReply(content, localResult) {
  const { apiBaseUrl, modelName, apiKey } = state.settings;
  if (!apiBaseUrl || !apiKey) {
    return buildLocalReply(localResult);
  }

  const response = await fetch(apiBaseUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: modelName || "gpt-4.1-mini",
      temperature: 0.25,
      messages: [
        {
          role: "system",
          content:
            "你是贵州统计指标匹配 Agent。必须优先使用给定指标匹配结果；匹配不足时，提出公开联网检索方向和谨慎的统计分析报告，不编造具体数据。",
        },
        {
          role: "user",
          content: `匹配策略：\n${els.knowledgeBase.value}\n\n用户问题：\n${content}\n\n本地指标匹配结果：\n${JSON.stringify(localResult, null, 2)}`,
        },
      ],
    }),
  });

  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  const data = await response.json();
  return data.choices?.[0]?.message?.content?.trim() || buildLocalReply(localResult);
}

function analyzeQuestion(question) {
  const route = routeQuestion(question);
  const matches = searchMetrics(question, 8, route);
  const topScore = matches[0]?.score || 0;
  const coverage = topScore >= 0.68 ? "full" : topScore >= 0.36 ? "partial" : "low";
  const inferredTopics = inferTopics(question, matches, route);
  const gaps = inferGaps(question, matches, coverage);
  return {
    question,
    optimizedVersion: state.metricPayload?.version || "semantic_graphrag_optimized_offline",
    route,
    inferredTopics,
    coverage,
    topScore,
    matches,
    gaps,
    webQueries: buildWebQueries(question, gaps, inferredTopics),
  };
}

function routeQuestion(question) {
  const categories = [...groupByCategory().keys()];
  const mentionedCategories = categories.filter((category) => category && question.includes(category));
  let queryType = "local";

  if (mentionedCategories.length >= 2 || compareWords.some((word) => question.includes(word))) {
    queryType = "cross_category";
  } else if (localWords.some((word) => question.includes(word))) {
    queryType = "local";
  } else if (globalWords.some((word) => question.includes(word)) && !/多少|数量|数/.test(question)) {
    queryType = "global";
  }

  const rankedCategories = mentionedCategories.length
    ? mentionedCategories.map((category) => ({ category, score: 0.98, reason: "命中大类名称" }))
    : rankCategories(question, 3);

  return {
    queryType,
    categories: rankedCategories.map((item) => item.category),
    rankedCategories,
    reason: mentionedCategories.length ? "命中大类名称" : "根据大类摘要和指标名称推断",
  };
}

function rankCategories(question, limit = 3) {
  const byCategory = metricsByCategory();
  const qNorm = normalizeText(question);
  const qCore = stripStopWords(question);
  const grams = makeNgrams(qCore || qNorm);
  return [...byCategory.entries()]
    .map(([category, metrics]) => {
      const sample = metrics
        .slice(0, 80)
        .map((metric) => [metric.name, metric.desc, metric.object, metric.property, ...metric.aliases].join(" "))
        .join(" ");
      const searchable = normalizeText(`${category} ${sample}`);
      let score = category && qNorm.includes(normalizeText(category)) ? 0.98 : 0;
      const hits = grams.filter((gram) => searchable.includes(gram)).length;
      score = Math.max(score, grams.length ? hits / grams.length : 0);
      return { category, score, reason: score >= 0.98 ? "命中大类名称" : "根据大类指标摘要推断" };
    })
    .sort((a, b) => b.score - a.score)
    .slice(0, limit);
}

function searchMetrics(question, limit = 8, route = routeQuestion(question)) {
  const qNorm = normalizeText(question);
  const qCore = stripStopWords(qNorm);
  const grams = makeNgrams(qCore || qNorm);
  const routeCategories = new Set(route.categories || []);

  const candidates = state.metrics
    .map((metric) => scoreMetric(metric, question, qNorm, qCore, grams, routeCategories))
    .filter((item) => item.score >= 0.08)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit);

  if (route.queryType === "global" || route.queryType === "cross_category") {
    const byCategory = metricsByCategory();
    const globalMatches = [];
    for (const category of route.categories || []) {
      const categoryMetrics = byCategory.get(category) || [];
      const representatives = categoryMetrics
        .map((metric) => scoreMetric(metric, question, qNorm, qCore, grams, routeCategories))
        .sort((a, b) => b.score - a.score)
        .slice(0, 8);
      for (const scored of representatives) {
        globalMatches.push({
          ...scored,
          score: Math.max(scored.score, 0.48),
          reason: `命中大类社区「${category}」；${scored.reason}`,
        });
      }
    }
    return [...globalMatches, ...candidates]
      .sort((a, b) => b.score - a.score)
      .filter(uniqueByName)
      .slice(0, limit);
  }

  return candidates;
}

function scoreMetric(metric, question, qNorm, qCore, grams, routeCategories = new Set()) {
  const fields = [
    metric.name,
    metric.category,
    metric.desc,
    metric.source,
    metric.object,
    metric.property,
    ...metric.aliases,
    ...metric.conditions,
  ].filter(Boolean);
  const searchText = normalizeText(fields.join(" "));
  const metricName = normalizeText(metric.name);
  const category = normalizeText(metric.category);
  const aliases = metric.aliases.map(normalizeText);
  const fuzzy = fuzzyScore(qCore || qNorm, searchText);
  const coverage = coverageScore(question, metric.name);
  const semantic = semanticScore(question, metric);
  const routeBonus = routeCategories.has(metric.category) ? 0.16 : 0;
  const penalty = broadMetricPenalty(question, metric);

  let score = 0.35 * fuzzy + 0.30 * coverage + 0.16 + 0.09 * semantic + routeBonus - penalty;
  const reasons = [];

  if (metricName && (qNorm.includes(metricName) || (qCore.length >= 2 && metricName.includes(qCore)))) {
    score += 0.2;
    reasons.push("指标名称直接相关");
  }
  if (aliases.some((alias) => alias.length >= 2 && (qNorm.includes(alias) || (qCore.length >= 2 && alias.includes(qCore))))) {
    score += 0.14;
    reasons.push("命中别名或常见说法");
  }
  if (category && qNorm.includes(category)) {
    score += 0.08;
    reasons.push(`命中分类「${metric.category}」`);
  }

  if (metric.isBoolean && /是否|有没有|有无|能否|通不通|做了没有/.test(question)) {
    score += 0.12;
    reasons.push("问题是是否类判断");
  }
  if (metric.desc && normalizeText(metric.desc).includes(qCore) && qCore.length >= 3) {
    score += 0.12;
    reasons.push("口径说明相关");
  }
  if (coverage >= 0.92) score += 0.2;
  else if (coverage >= 0.8) score += 0.1;
  if (routeBonus) reasons.push(`路由大类「${metric.category}」加权`);

  score = Math.max(0, Math.min(0.99, score));
  if (!reasons.length && (fuzzy > 0 || coverage > 0)) {
    reasons.push(`optimized 离线检索：字面=${fuzzy.toFixed(2)}；覆盖=${coverage.toFixed(2)}；骨架=${semantic.toFixed(2)}；惩罚=${penalty.toFixed(2)}`);
  }

  return {
    name: metric.name,
    category: metric.category,
    desc: metric.desc,
    source: metric.source,
    score,
    reason: reasons.join("；") || "弱相关",
  };
}

function inferTopics(question, matches, route) {
  const categories = [...new Set([...(route.categories || []), ...matches.slice(0, 5).map((item) => item.category)].filter(Boolean))];
  const keywords = stripStopWords(normalizeText(question))
    .split("")
    .filter((char, index, arr) => char && arr.indexOf(char) === index)
    .slice(0, 12);
  return { categories, keywords };
}

function inferGaps(question, matches, coverage) {
  const gaps = [];
  if (coverage !== "full") {
    gaps.push("现有指标匹配度不足，需要补充公开统计口径或相关指标名称。");
  }
  if (/近年|近几年|趋势|变化|恢复|增长|下降|对比|比较/.test(question)) {
    gaps.push("需要时间序列数据，至少包含年份、地区和指标值。");
  }
  if (/全国|周边|其他省|排名|比较|对比/.test(question)) {
    gaps.push("需要外部地区或全国口径数据用于对比。");
  }
  if (!matches.some((item) => item.desc)) {
    gaps.push("命中指标缺少口径说明，正式报告前需要核对定义。");
  }
  return gaps;
}

function buildWebQueries(question, gaps, topics) {
  if (!gaps.length) return [];
  const core = stripStopWords(question).replace(/\s+/g, " ").trim();
  const categoryPart = topics.categories.slice(0, 2).join(" ");
  const base = [core, categoryPart].filter(Boolean).join(" ");
  return webSourceHints.slice(0, 4).map((source) => `${source} ${base}`.trim());
}

function fuzzyScore(query, text) {
  const q = normalizeText(query);
  const t = normalizeText(text);
  if (!q || !t) return 0;
  if (t.includes(q) || q.includes(t)) return 0.96;
  const grams = makeNgrams(q);
  if (!grams.length) return 0;
  return grams.filter((gram) => t.includes(gram)).length / grams.length;
}

function charCoverageScore(query, metricName) {
  const q = normalizeForMatch(query);
  const m = normalizeForMatch(metricName);
  const core = queryCoreText(query);
  if (!m) return 0;
  if (m.includes(q) || q.includes(m) || (core && core === m)) return 1;
  if (core && (core.includes(m) || m.includes(core))) return 0.92;
  return [...m].filter((char) => q.includes(char)).length / Math.max([...m].length, 1);
}

function tokenCoverageScore(query, metricName) {
  const q = normalizeForMatch(query);
  const chars = [...normalizeForMatch(metricName)];
  if (!chars.length) return 0;
  const chunks = [];
  for (let i = 0; i < chars.length; i += 2) {
    chunks.push(chars.slice(i, i + 2).join(""));
  }
  return chunks.filter((chunk) => chunk && q.includes(chunk)).length / chunks.length;
}

function coverageScore(query, metricName) {
  return 0.65 * charCoverageScore(query, metricName) + 0.35 * tokenCoverageScore(query, metricName);
}

function semanticScore(query, metric) {
  let score = 0;
  for (const alias of metric.aliases) {
    if (alias.length >= 3 && (query.includes(alias) || alias.includes(query))) {
      score = Math.max(score, 0.35);
    }
  }
  if (metric.object && metric.object.length >= 2 && query.includes(metric.object)) score += 0.12;
  for (const condition of metric.conditions) {
    if (condition.length >= 2 && query.includes(condition)) score += 0.12;
  }
  if (metric.property === "是否" && /是否|有没有|有无|能否|做了没有/.test(query)) {
    score += 0.18;
  } else if (metric.property && metric.property.length >= 2 && query.includes(metric.property)) {
    score += 0.08;
  }
  if (metric.isBroadMetric && !query.includes(metric.name)) score -= 0.18;
  return Math.max(0, Math.min(score, 0.55));
}

function broadMetricPenalty(query, metric) {
  const normalizedMetric = normalizeForMatch(metric.name);
  const normalizedQuery = normalizeForMatch(query);
  if (normalizedMetric && normalizedQuery.includes(normalizedMetric)) return 0;
  if (broadMetricNames.has(metric.name)) return 0.22;
  if (normalizedMetric.length <= 3 && /数|量|人|户/.test(metric.name)) return 0.18;
  if (metric.isBroadMetric) return 0.12;
  if (metric.name.endsWith("情况") && !query.includes(metric.name)) return 0.12;
  if (/是否|有没有|有无|能否|做了没有/.test(query) && metric.property !== "是否") return 0.1;
  return 0;
}

function normalizeForMatch(value) {
  return String(value || "").replace(/[ \t\n\r（）()，,：:、\-_]/g, "").trim();
}

function queryCoreText(query) {
  let core = normalizeForMatch(query);
  for (const word of [...stopWords].sort((a, b) => b.length - a.length)) {
    core = core.replaceAll(normalizeForMatch(word), "");
  }
  return core.trim();
}

function uniqueByName(item, index, array) {
  return array.findIndex((candidate) => candidate.name === item.name) === index;
}

function buildLocalReply(result) {
  const matchLines = result.matches.length
    ? result.matches
        .slice(0, 6)
        .map((item, index) => {
          const source = item.source ? `；来源：${item.source}` : "";
          const desc = item.desc ? `\n   口径：${truncate(item.desc, 92)}` : "";
          return `${index + 1}. ${item.name}（${item.category}，匹配度 ${Math.round(item.score * 100)}%）\n   推荐理由：${item.reason}${source}${desc}`;
        })
        .join("\n")
    : "没有在现有指标集中找到足够可靠的匹配。";

  const coverageText = {
    full: "现有指标基本可以覆盖这个问题。",
    partial: "现有指标只能覆盖一部分，需要补充口径或数据。",
    low: "现有指标匹配较弱，建议进入联网补充检索。",
  }[result.coverage];

  const gapLines = result.gaps.length
    ? result.gaps.map((gap) => `- ${gap}`).join("\n")
    : "- 暂未发现明显缺口，优先使用上面的授权指标。";

  const webLines = result.webQueries.length
    ? result.webQueries
        .map((query) => {
          const url = `https://www.bing.com/search?q=${encodeURIComponent(query)}`;
          return `- ${query}\n  ${url}`;
        })
        .join("\n")
    : "- 当前匹配较充分，暂不需要联网补充。";

  return `问题理解：
你想围绕“${result.question}”寻找可用统计指标，并据此形成一个简短分析口径。

检索策略：
当前使用 ${result.optimizedVersion}。问题被路由为 ${result.route.queryType}，优先关注 ${result.route.categories.join("、") || "全部分类"}。

现有指标匹配：
${coverageText}
${matchLines}

缺口判断：
${gapLines}

联网补充建议：
${webLines}

简短统计分析报告：
建议先以上述匹配度最高的指标作为主指标，再用同分类下的辅助指标交叉验证。如果问题涉及趋势，应按年度整理指标值，观察总量变化和结构变化；如果涉及比较，应统一统计口径后再做地区或时间对比。对于联网补充得到的公开资料，需要保留来源、发布时间和口径说明，正式结论仍以贵州统计局授权指标和数据为准。`;
}

async function loadProtectedMetrics() {
  saveSettings(false);
  const endpoint = els.metricEndpoint.value.trim();
  const token = els.metricAccessToken.value.trim();
  if (!endpoint || !token) {
    await loadBuiltInMetrics();
    addMessage("assistant", "已重新加载内置贵州统计指标集。若要加载私有后端指标，请填写接口和访问令牌。");
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
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    applyMetricPayload(await response.json(), "后端授权指标集");
    addMessage("assistant", `已加载 ${state.metrics.length} 个后端授权指标，可用于后续匹配。`);
  } catch (error) {
    addMessage("assistant", `指标集加载失败：${error.message}`);
  } finally {
    els.loadMetrics.innerHTML = '<i data-lucide="key-round" aria-hidden="true"></i>重新加载指标集';
    refreshIcons();
  }
}

function normalizeMetric(item) {
  const name = String(item.name || item.metric || item.metric_name || "").trim();
  if (!name) return null;
  return {
    name,
    category: String(item.category || "未分类").trim(),
    desc: String(item.desc || item.description || item.definition || "").trim(),
    aliases: Array.isArray(item.aliases)
      ? item.aliases.map(String).filter(Boolean)
      : String(item.aliases || "").split(/[;；,，]/).filter(Boolean),
    source: String(item.source || "").trim(),
    object: String(item.object || "").trim(),
    property: String(item.property || "").trim(),
    conditions: Array.isArray(item.conditions)
      ? item.conditions.map(String).filter(Boolean)
      : String(item.conditions || "").split(/[;；,，]/).filter(Boolean),
    isBoolean: Boolean(item.isBoolean || item.is_boolean === true || item.is_boolean === "True"),
    isBroadMetric: Boolean(item.isBroadMetric || item.is_broad_metric === true || item.is_broad_metric === "True"),
  };
}

function normalizeText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^\p{Script=Han}a-z0-9]/gu, "");
}

function stripStopWords(value) {
  let text = normalizeText(value);
  for (const word of stopWords) {
    text = text.replaceAll(normalizeText(word), "");
  }
  return text;
}

function makeNgrams(text) {
  const clean = normalizeText(text);
  const grams = new Set();
  for (let size of [2, 3]) {
    for (let i = 0; i <= clean.length - size; i += 1) {
      grams.add(clean.slice(i, i + size));
    }
  }
  return [...grams].slice(0, 80);
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
  refreshIcons();
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
    refreshIcons();
  }, 1200);
}

function resetChat() {
  state.messages = [];
  persistMessages();
  renderMessages();
  addMessage("assistant", "对话已清空。请输入新的贵州统计指标问题。");
}

function exportChat() {
  const lines = state.messages
    .map((item) => `## ${item.role === "user" ? "用户" : "Agent"}\n${item.content}`)
    .join("\n\n");
  const blob = new Blob([lines], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `guizhou-indicator-report-${new Date().toISOString().slice(0, 10)}.md`;
  link.click();
  URL.revokeObjectURL(url);
}

function truncate(value, maxLength) {
  const text = String(value || "");
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function refreshIcons() {
  if (window.lucide?.createIcons) {
    window.lucide.createIcons();
  }
}

document.addEventListener("DOMContentLoaded", init);
