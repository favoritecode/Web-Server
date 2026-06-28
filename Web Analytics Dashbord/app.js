const state = { result: null, pages: [], selected: 0 };
const $ = (id) => document.getElementById(id);

function setStatus(text, busy = false) {
  const box = $("scanStatus");
  box.innerHTML = `<span class="pulse"></span><span>${escapeHtml(text)}</span>`;
  box.classList.toggle("busy", busy);
}

function scoreClass(score) {
  if (score >= 80) return "good";
  if (score < 60) return "bad";
  return "warn";
}

function setScores(scores = {}) {
  const items = [
    ["seoScore", "seoBar", scores.seo],
    ["speedScore", "speedBar", scores.speed],
    ["techScore", "techBar", scores.technical],
    ["contentScore", "contentBar", scores.content],
    ["spamScore", "spamBar", scores.spam],
  ];
  items.forEach(([scoreId, barId, value]) => {
    const score = Number.isFinite(value) ? Math.round(value) : 0;
    $(scoreId).textContent = score || "--";
    $(barId).style.width = `${score}%`;
  });
}

function renderResult(data) {
  state.result = data;
  state.pages = data.pages || [];
  state.selected = 0;
  setScores(data.scores || {});
  renderOverview(data);
  renderLists(data);
  renderPages();
  if (state.pages[0]) renderDetails(state.pages[0]);
  setStatus(`Scan complete: ${data.normalized_url || data.domain || "article"}`);
}

function renderOverview(data) {
  const overview = [
    ["Domain", data.domain || "Direct article"],
    ["Final URL", data.normalized_url || data.url || "Not available"],
    ["Host / Server", data.hosting?.server || "Unknown"],
    ["IP", data.hosting?.ip || "Unknown"],
    ["CMS / Platform", data.technology?.cms || "Unknown"],
    ["Theme / Template", data.technology?.theme || "Unknown"],
    ["Stack / Framework", data.technology?.stack || "Unknown"],
    ["SSL", data.hosting?.ssl || "Not checked"],
    ["Sitemap", data.discovery?.sitemap || "Not found"],
    ["Robots", data.discovery?.robots || "Not found"],
    ["Domain availability", data.availability?.status || "Not checked"],
    ["Availability note", data.availability?.message || "No availability check yet"],
  ];
  $("overviewList").innerHTML = overview.map(([k, v]) => `<div><dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd></div>`).join("");
  $("scanTime").textContent = data.scanned_at || "Just now";
}

function renderLists(data) {
  const technologies = data.technology?.items || [];
  $("techList").innerHTML = technologies.length ? technologies.map((x) => `<span>${escapeHtml(x)}</span>`).join("") : `<p class="notice">No clear technology signature detected.</p>`;
  $("techCount").textContent = technologies.length;
  list("goodList", data.good || []);
  list("issueList", data.issues || []);
  list("actionList", data.actions || []);
  $("goodCount").textContent = (data.good || []).length;
  $("issueCount").textContent = (data.issues || []).length;
}

function list(id, items) {
  $(id).innerHTML = (items.length ? items : ["No item detected yet."]).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
}

function renderPages() {
  const box = $("articleList");
  $("pageCount").textContent = `${state.pages.length} found`;
  box.innerHTML = "";
  if (!state.pages.length) {
    box.innerHTML = `<p class="notice">No article or page list available.</p>`;
    return;
  }
  state.pages.forEach((page, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `article-row ${index === state.selected ? "active" : ""}`;
    button.innerHTML = `
      <span><strong>${escapeHtml(page.title || "Untitled page")}</strong><small>${escapeHtml(page.url || "")}</small></span>
      <span class="score-pill ${scoreClass(page.score || 0)}">${Math.round(page.score || 0)}</span>
    `;
    button.addEventListener("click", () => {
      state.selected = index;
      renderPages();
      renderDetails(page);
    });
    box.appendChild(button);
  });
}

function renderDetails(page) {
  $("detailTitle").textContent = page.title || "Page Details";
  $("detailScore").textContent = `SEO ${Math.round(page.score || 0)}/100`;
  $("detailBody").innerHTML = `
    <section class="detail-section">
      <h3>Page metrics</h3>
      <div class="kv-grid">
        <div><span>Words</span>${page.words || 0}</div>
        <div><span>H1 / H2</span>${page.h1_count || 0} / ${page.h2_count || 0}</div>
        <div><span>Images missing alt</span>${page.images_missing_alt || 0}</div>
        <div><span>Load time</span>${page.load_ms || 0} ms</div>
      </div>
    </section>
    <section class="detail-section"><h3>Used / Good</h3><ul class="check-list">${items(page.good)}</ul></section>
    <section class="detail-section"><h3>Missing / Problems</h3><ul class="issue-list">${items(page.issues)}</ul></section>
    <section class="detail-section"><h3>SEO recommendations</h3><ul class="action-list">${items(page.actions)}</ul></section>
  `;
}

function items(values = []) {
  return (values.length ? values : ["No major item detected."]).map((x) => `<li>${escapeHtml(x)}</li>`).join("");
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Scan failed");
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

document.querySelectorAll(".mode-tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".mode-tab").forEach((tab) => tab.classList.toggle("active", tab === button));
    $("websitePanel").classList.toggle("active", button.dataset.mode === "website");
    $("articlePanel").classList.toggle("active", button.dataset.mode === "article");
  });
});

$("siteForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  setStatus("Scanning website, fetching pages...", true);
  try {
    const data = await postJson("/api/analytics/scan", {
      domain: $("domainInput").value.trim(),
      limit: Number($("scanLimit").value),
    });
    renderResult(data);
  } catch (error) {
    setStatus(error.message || "Scan failed");
  }
});

$("articleForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  setStatus("Analyzing article...", true);
  try {
    const data = await postJson("/api/analytics/article", {
      url: $("articleUrl").value.trim(),
      keyword: $("focusKeyword").value.trim(),
      content: $("articleContent").value,
    });
    renderResult(data);
  } catch (error) {
    setStatus(error.message || "Article analysis failed");
  }
});

setScores();

