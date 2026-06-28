const demoArticles = [
  {
    title: "How to choose a responsive Blogger template",
    url: "https://demo.blogspot.com/responsive-template.html",
    keyword: "responsive blogger template",
    meta: "A practical checklist for choosing a fast, mobile friendly Blogger template.",
    content:
      "A responsive Blogger template should be fast, readable, schema friendly and easy to customize. This guide explains mobile layout, navigation, heading structure, image optimization, internal links, Core Web Vitals and template cleanup for better SEO performance.",
  },
  {
    title: "Blogger SEO checklist for new posts",
    url: "https://demo.blogspot.com/blogger-seo-checklist.html",
    keyword: "blogger seo checklist",
    meta: "Use this Blogger SEO checklist before publishing every post.",
    content:
      "Before publishing a Blogger post, review the title, meta description, keyword placement, headings, alt text, internal links, external sources and content depth. A strong article answers search intent and avoids thin paragraphs.",
  },
  {
    title: "Fix slow loading widgets on Blogspot",
    url: "https://demo.blogspot.com/fix-slow-widgets.html",
    keyword: "slow blogger widgets",
    meta: "Find and remove slow widgets that hurt your Blogspot speed.",
    content:
      "Heavy ad scripts, old counters, social widgets and uncompressed images can make a Blogspot site slow. Remove unused widgets, defer scripts, compress images and keep only the tools that improve reader experience.",
  },
];

const state = {
  articles: [],
  selectedIndex: 0,
};

const $ = (id) => document.getElementById(id);

const checks = {
  good: [
    "Mobile responsive template detected",
    "Readable title structure found",
    "Internal linking pattern is present",
    "Content has clear topical focus",
  ],
  missing: [
    "Add Article schema or BlogPosting schema",
    "Compress large images and set width/height",
    "Add descriptive alt text to all article images",
    "Improve meta descriptions under 160 characters",
    "Remove unused widgets that delay page rendering",
  ],
  recommend: [
    "Use one H1, then organize sections with H2 and H3 headings.",
    "Add FAQ blocks when the topic has direct search questions.",
    "Keep keyword usage natural and include related entities.",
    "Link every new post to at least two older relevant posts.",
  ],
};

function clampScore(score) {
  return Math.max(1, Math.min(100, Math.round(score)));
}

function scoreClass(score) {
  if (score >= 80) return "good";
  if (score >= 60) return "warn";
  return "bad";
}

function wordCount(text) {
  return (text || "").trim().split(/\s+/).filter(Boolean).length;
}

function hasKeyword(text, keyword) {
  if (!keyword) return false;
  return (text || "").toLowerCase().includes(keyword.toLowerCase());
}

function analyzeArticle(article) {
  const title = article.title || "";
  const meta = article.meta || "";
  const content = article.content || "";
  const keyword = article.keyword || "";
  const words = wordCount(content);
  const headingCount = (content.match(/<h[2-3]/gi) || []).length;
  const imageCount = (content.match(/<img/gi) || []).length;
  const links = (content.match(/https?:\/\//gi) || []).length;

  let seo = 48;
  if (title.length >= 35 && title.length <= 65) seo += 12;
  if (meta.length >= 80 && meta.length <= 160) seo += 12;
  if (hasKeyword(title, keyword)) seo += 10;
  if (hasKeyword(content, keyword)) seo += 10;
  if (words >= 350) seo += 8;

  let contentValue = 45;
  if (words >= 500) contentValue += 18;
  else if (words >= 250) contentValue += 10;
  if (headingCount > 0 || words >= 300) contentValue += 8;
  if (links > 0) contentValue += 7;
  if (content.length > 0) contentValue += 12;

  const missing = [];
  const used = [];
  const remove = [];
  const add = [];

  if (title) used.push("SEO title");
  else missing.push("Article title");

  if (meta) used.push("Meta description");
  else missing.push("Meta description");

  if (keyword) used.push("Focus keyword");
  else missing.push("Focus keyword");

  if (hasKeyword(title, keyword)) used.push("Keyword in title");
  else add.push("Place the focus keyword in the title naturally");

  if (hasKeyword(content, keyword)) used.push("Keyword inside content");
  else add.push("Mention the focus keyword in the first 100 words");

  if (words < 350) add.push("Expand content depth with examples, FAQs and original insight");
  if (meta.length > 160) remove.push("Shorten meta description to avoid search snippet truncation");
  if (title.length > 65) remove.push("Shorten the title so the main keyword stays visible");
  if (imageCount === 0) add.push("Add relevant images with descriptive alt text");
  if (links === 0) add.push("Add internal links and trusted external references");

  return {
    ...article,
    seo: clampScore(seo),
    speed: clampScore(76 - imageCount * 3 + (content.includes("<script") ? -10 : 6)),
    contentValue: clampScore(contentValue),
    tech: clampScore(82 + (article.url ? 4 : -8)),
    words,
    used,
    missing,
    add,
    remove,
  };
}

function makeArticleFromLine(line, index) {
  const trimmed = line.trim();
  const title = trimmed.startsWith("http")
    ? trimmed.split("/").filter(Boolean).pop().replace(/[-_]/g, " ").replace(/\.\w+$/, "")
    : trimmed;

  return {
    title: title || `Article ${index + 1}`,
    url: trimmed.startsWith("http") ? trimmed : "",
    keyword: title.split(" ").slice(0, 3).join(" "),
    meta: `Useful guide about ${title || "this article"} for search readers.`,
    content: `${title} article content should include clear headings, original examples, internal links, image alt text and a direct answer to the search intent. Add more details to improve content value and SEO completeness.`,
  };
}

function setScores(scores) {
  const entries = [
    ["seoScore", "seoMeter", scores.seo],
    ["speedScore", "speedMeter", scores.speed],
    ["contentScore", "contentMeter", scores.contentValue],
    ["techScore", "techMeter", scores.tech],
  ];

  entries.forEach(([scoreId, meterId, value]) => {
    $(scoreId).textContent = value;
    $(meterId).style.width = `${value}%`;
  });

  const avg = clampScore((scores.seo + scores.speed + scores.contentValue + scores.tech) / 4);
  $("sidebarScore").textContent = `${avg}%`;
  $("sidebarNote").textContent = avg >= 80 ? "Strong foundation" : avg >= 60 ? "Needs cleanup" : "High priority fixes";
}

function renderList(id, items) {
  const list = $(id);
  list.innerHTML = "";
  items.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    list.appendChild(li);
  });
}

function renderArticles() {
  const container = $("articles");
  container.innerHTML = "";
  $("articleCount").textContent = `${state.articles.length} articles`;

  state.articles.forEach((article, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `article-row ${index === state.selectedIndex ? "active" : ""}`;
    button.innerHTML = `
      <span>
        <strong>${escapeHtml(article.title)}</strong>
        <span>${escapeHtml(article.url || "Draft / pasted article")}</span>
      </span>
      <span class="score-pill ${scoreClass(article.seo)}">${article.seo}</span>
    `;
    button.addEventListener("click", () => {
      state.selectedIndex = index;
      renderArticles();
      renderArticleDetails(article);
    });
    container.appendChild(button);
  });
}

function renderArticleDetails(article) {
  $("detailTitle").textContent = article.title || "Article details";
  $("detailScore").textContent = `SEO ${article.seo}/100`;
  $("articleDetails").innerHTML = `
    <div class="detail-section">
      <h3>Content value</h3>
      <p>${article.contentValue}/100 score, ${article.words} words. ${contentAdvice(article)}</p>
    </div>
    <div class="detail-section">
      <h3>Used in article</h3>
      <div class="tag-line">${tags(article.used)}</div>
    </div>
    <div class="detail-section">
      <h3>Missing</h3>
      <ul class="issue-list">${listItems(article.missing.length ? article.missing : ["No major missing basics"])}</ul>
    </div>
    <div class="detail-section">
      <h3>Add for better SEO</h3>
      <ul class="recommend-list">${listItems(article.add.length ? article.add : ["Add recent examples and internal links for extra authority"])}</ul>
    </div>
    <div class="detail-section">
      <h3>Remove or reduce</h3>
      <ul class="issue-list">${listItems(article.remove.length ? article.remove : ["No urgent removal detected"])}</ul>
    </div>
  `;
}

function contentAdvice(article) {
  if (article.words < 250) return "Content is thin; add examples, steps and FAQs.";
  if (article.contentValue < 75) return "Content is useful but needs stronger structure and references.";
  return "Content has solid topical coverage and can rank with technical cleanup.";
}

function tags(items) {
  return (items.length ? items : ["No confirmed SEO elements"]).map((item) => `<span>${escapeHtml(item)}</span>`).join("");
}

function listItems(items) {
  return items.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function aggregateScores(articles) {
  if (!articles.length) {
    return { seo: 68, speed: 72, contentValue: 64, tech: 70 };
  }
  const sum = articles.reduce(
    (acc, article) => {
      acc.seo += article.seo;
      acc.speed += article.speed;
      acc.contentValue += article.contentValue;
      acc.tech += article.tech;
      return acc;
    },
    { seo: 0, speed: 0, contentValue: 0, tech: 0 },
  );

  return {
    seo: clampScore(sum.seo / articles.length),
    speed: clampScore(sum.speed / articles.length),
    contentValue: clampScore(sum.contentValue / articles.length),
    tech: clampScore(sum.tech / articles.length),
  };
}

function runSiteAudit() {
  const rawArticles = $("articleList").value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const articles = (rawArticles.length ? rawArticles.map(makeArticleFromLine) : demoArticles).map(analyzeArticle);

  state.articles = articles;
  state.selectedIndex = 0;

  $("hostOutput").textContent = $("siteHost").value;
  $("templateOutput").textContent = $("templateName").value || "Template not provided";
  $("pluginsOutput").textContent = $("pluginList").value || "No plugin/widget list provided";
  $("bugsOutput").textContent = buildBugOutput($("pluginList").value, $("templateName").value);
  $("overviewBadge").textContent = $("siteUrl").value ? urlSafeHost($("siteUrl").value) : "Local audit";

  renderList("goodList", checks.good);
  renderList("missingList", checks.missing);
  renderList("recommendList", checks.recommend);
  $("goodCount").textContent = checks.good.length;
  $("missingCount").textContent = checks.missing.length;

  setScores(aggregateScores(articles));
  renderArticles();
  renderArticleDetails(articles[0]);
}

function buildBugOutput(plugins, template) {
  const issues = [];
  if (!template) issues.push("template name missing");
  if (!plugins) issues.push("plugin list missing");
  if ((plugins || "").toLowerCase().includes("ads")) issues.push("ad script speed risk");
  if (!issues.length) issues.push("no critical bug from provided data");
  return issues.join(", ");
}

function urlSafeHost(value) {
  try {
    return new URL(value).host;
  } catch {
    return "Custom URL";
  }
}

function runArticleAudit() {
  const article = analyzeArticle({
    title: $("singleTitle").value || "Untitled article",
    url: $("singleUrl").value,
    keyword: $("singleKeyword").value,
    meta: $("singleMeta").value,
    content: $("singleContent").value,
  });

  state.articles = [article];
  state.selectedIndex = 0;
  setScores(article);
  renderArticles();
  renderArticleDetails(article);
  $("overviewBadge").textContent = "Article";
  $("hostOutput").textContent = article.url ? urlSafeHost(article.url) : "Direct paste";
  $("templateOutput").textContent = "Not checked in article-only mode";
  $("pluginsOutput").textContent = "Not checked in article-only mode";
  $("bugsOutput").textContent = article.missing.join(", ") || "No critical article bug";

  renderList("goodList", article.used);
  renderList("missingList", article.missing.length ? article.missing : ["No major missing basics"]);
  renderList("recommendList", article.add.length ? article.add : checks.recommend);
  $("goodCount").textContent = article.used.length;
  $("missingCount").textContent = article.missing.length;
}

function switchMode(mode) {
  document.querySelectorAll(".mode-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === mode);
  });
  $("sitePanel").classList.toggle("active", mode === "site");
  $("articlePanel").classList.toggle("active", mode === "article");
}

function loadDemo() {
  $("siteUrl").value = "https://demo.blogspot.com";
  $("siteHost").value = "Blogger / Blogspot";
  $("templateName").value = "Responsive custom Blogger theme";
  $("pluginList").value = "Adsense, Search box, Related posts, Email subscription";
  $("articleList").value = demoArticles.map((article) => article.url).join("\n");
  $("singleTitle").value = demoArticles[1].title;
  $("singleKeyword").value = demoArticles[1].keyword;
  $("singleMeta").value = demoArticles[1].meta;
  $("singleUrl").value = demoArticles[1].url;
  $("singleContent").value = demoArticles[1].content;
  runSiteAudit();
}

document.querySelectorAll(".mode-button").forEach((button) => {
  button.addEventListener("click", () => switchMode(button.dataset.mode));
});

$("runSiteAudit").addEventListener("click", runSiteAudit);
$("runArticleAudit").addEventListener("click", runArticleAudit);
$("loadDemo").addEventListener("click", loadDemo);

loadDemo();
