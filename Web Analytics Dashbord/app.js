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
  $("pdfButton").disabled = false;
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
  $("pdfButton").disabled = true;
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
  $("pdfButton").disabled = true;
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


$("pdfButton").addEventListener("click", () => {
  if (!state.result) {
    setStatus("Run an analysis before downloading PDF.");
    return;
  }
  downloadPdfReport(state.result);
});

function downloadPdfReport(data) {
  const title = "FavoriteWeb Analysis Report";
  const lines = buildReportLines(data);
  const pdf = makePdf(title, lines);
  const safeName = cleanFileName(data.domain || data.normalized_url || data.url || "analysis");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(pdf);
  link.download = `${safeName}-analysis-report.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  setStatus("PDF report downloaded.");
}

function buildReportLines(data) {
  const scores = data.scores || {};
  const tech = data.technology || {};
  const hosting = data.hosting || {};
  const discovery = data.discovery || {};
  const availability = data.availability || {};
  const pages = data.pages || [];
  return [
    "Report generated: " + new Date().toLocaleString(),
    "Scanned at: " + (data.scanned_at || "Not available"),
    "",
    "OVERVIEW",
    "Domain: " + (data.domain || "Direct article"),
    "Final URL: " + (data.normalized_url || data.url || "Not available"),
    "Server: " + (hosting.server || "Unknown"),
    "IP: " + (hosting.ip || "Unknown"),
    "SSL: " + (hosting.ssl || "Not checked"),
    "CMS / Platform: " + (tech.cms || "Unknown"),
    "Theme / Template: " + (tech.theme || "Unknown"),
    "Stack / Framework: " + (tech.stack || "Unknown"),
    "Sitemap: " + (discovery.sitemap || "Not found"),
    "Robots: " + (discovery.robots || "Not found"),
    "Domain availability: " + (availability.status || "Not checked"),
    "Availability note: " + (availability.message || "No availability check yet"),
    "",
    "SCORES",
    "SEO Score: " + scoreText(scores.seo),
    "Speed Health: " + scoreText(scores.speed),
    "Technical: " + scoreText(scores.technical),
    "Content Value: " + scoreText(scores.content),
    "Spam Score: " + scoreText(scores.spam),
    "",
    "DETECTED TECHNOLOGY",
    ...bulletLines(tech.items || []),
    "",
    "GOOD THINGS",
    ...bulletLines(data.good || []),
    "",
    "MISSING / BUGS",
    ...bulletLines(data.issues || []),
    "",
    "SEO ACTION PLAN",
    ...bulletLines(data.actions || []),
    "",
    "PAGES / ARTICLES",
    ...pages.slice(0, 20).flatMap((page, index) => [
      `${index + 1}. ${page.title || "Untitled page"}`,
      `   URL: ${page.url || "Not available"}`,
      `   SEO: ${Math.round(page.score || 0)}/100 | Words: ${page.words || 0} | H1/H2: ${page.h1_count || 0}/${page.h2_count || 0} | Missing alt: ${page.images_missing_alt || 0}`,
      ...bulletLines([...(page.issues || []).slice(0, 3), ...(page.actions || []).slice(0, 3)], "   - "),
      "",
    ]),
  ];
}

function bulletLines(values, prefix = "- ") {
  return values.length ? values.map((value) => prefix + value) : ["- No item detected."];
}

function scoreText(value) {
  return Number.isFinite(value) ? `${Math.round(value)}/100` : "Not available";
}

function makePdf(title, lines) {
  const width = 595;
  const height = 842;
  const margin = 42;
  const lineHeight = 14;
  const maxChars = 92;
  const pages = [];
  let current = [];
  const usableLines = 52;

  const wrapped = [title, ""].concat(lines).flatMap((line) => wrapPdfLine(line, maxChars));
  wrapped.forEach((line) => {
    if (current.length >= usableLines) {
      pages.push(current);
      current = [];
    }
    current.push(line);
  });
  if (current.length) pages.push(current);

  const objects = [];
  objects.push("<< /Type /Catalog /Pages 2 0 R >>");
  const pageRefs = pages.map((_, index) => `${3 + index * 2} 0 R`).join(" ");
  objects.push(`<< /Type /Pages /Kids [${pageRefs}] /Count ${pages.length} >>`);

  pages.forEach((pageLines, index) => {
    const pageObj = 3 + index * 2;
    const contentObj = pageObj + 1;
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${width} ${height}] /Resources << /Font << /F1 ${3 + pages.length * 2} 0 R >> >> /Contents ${contentObj} 0 R >>`);
    const content = pageLines.map((line, lineIndex) => {
      const size = lineIndex === 0 && index === 0 ? 18 : 10;
      const y = height - margin - lineIndex * lineHeight;
      return `BT /F1 ${size} Tf ${margin} ${y} Td (${escapePdfText(line)}) Tj ET`;
    }).join("\n");
    objects.push(`<< /Length ${content.length} >>\nstream\n${content}\nendstream`);
  });
  objects.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");

  let output = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(output.length);
    output += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xrefAt = output.length;
  output += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  offsets.slice(1).forEach((offset) => {
    output += `${String(offset).padStart(10, "0")} 00000 n \n`;
  });
  output += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefAt}\n%%EOF`;
  return new Blob([output], { type: "application/pdf" });
}

function wrapPdfLine(value, maxChars) {
  const text = pdfSafe(value || "");
  if (!text) return [""];
  const words = text.split(/\s+/);
  const lines = [];
  let line = "";
  words.forEach((word) => {
    if ((line + " " + word).trim().length > maxChars) {
      if (line) lines.push(line);
      while (word.length > maxChars) {
        lines.push(word.slice(0, maxChars));
        word = word.slice(maxChars);
      }
      line = word;
    } else {
      line = (line + " " + word).trim();
    }
  });
  if (line) lines.push(line);
  return lines;
}

function pdfSafe(value) {
  return String(value ?? "").replace(/[\u2018\u2019]/g, "'").replace(/[\u201c\u201d]/g, '"').replace(/[^\x20-\x7E]/g, "?");
}

function escapePdfText(value) {
  return pdfSafe(value).replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
}

function cleanFileName(value) {
  return String(value).toLowerCase().replace(/^https?:\/\//, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "analysis";
}

setScores();

