let loadedItems = [];
let downloadStates = {};

// ===================================================================
// Auto-detect video ID from URL path or injected __VIDEO_ID__
// e.g. https://khan.favoriteweb.net/download/YwfH_-6rJkQ
// ===================================================================
(function autoDetectVideoId() {
  var videoId = null;
  
  // First check if backend injected __VIDEO_ID__
  if (typeof window.__VIDEO_ID__ !== 'undefined' && window.__VIDEO_ID__) {
    videoId = window.__VIDEO_ID__;
  } else {
    // Fallback: parse from URL path
    var path = window.location.pathname;
    var match = path.match(/^\/download\/([a-zA-Z0-9_-]{6,})$/);
    if (match) {
      videoId = match[1];
    }
  }
  
  if (videoId) {
    var youtubeUrl = "https://www.youtube.com/watch?v=" + videoId;
    var textarea = document.getElementById("url");
    if (textarea) {
      textarea.value = youtubeUrl;
      // Auto-trigger download after a short delay to ensure page is loaded
      setTimeout(function() {
        getVideo();
      }, 300);
    }
  }
})();

// ===================================================================
// URL Parsing - spaces between links = separate URLs
// ===================================================================
function getUrls() {
  const raw = document.getElementById("url").value;
  if (!raw.trim()) return [];
  return raw.trim().split(/\s+/).filter(Boolean);
}

// ===================================================================
// Fetch video info from server
// ===================================================================
async function getVideo() {
  const urls = getUrls();
  const button = document.getElementById("downloadBtn");
  const result = document.getElementById("result");

  if (!urls.length) {
    alert("Paste at least one video link");
    return;
  }

  loadedItems = [];
  button.disabled = true;
  button.textContent = "Loading\u2026";
  result.innerHTML = `<p class="status">Fetching details for ${urls.length} link${urls.length > 1 ? "s" : ""}\u2026</p>`;

  try {
    const responses = await Promise.all(urls.map(loadInfo));
    loadedItems = responses;
    renderResults(responses);
  } finally {
    button.disabled = false;
    button.textContent = "Get formats";
  }
}

async function loadInfo(url, index) {
  try {
    const res = await fetch("/download/api?url=" + encodeURIComponent(url));
    const data = await res.json();
    if (!res.ok || data.error) {
      if (isSocialUrl(url)) return normalizeItem(socialFallbackData(url), url, index);
      return { inputUrl: url, index, error: data.error || "Video not available" };
    }
    return normalizeItem(data, url, index);
  } catch {
    if (isSocialUrl(url)) return normalizeItem(socialFallbackData(url), url, index);
    return { inputUrl: url, index, error: "Could not load info" };
  }
}

function isSocialUrl(url) {
  return /(instagram\.com|facebook\.com|fb\.watch|pin\.it|pinterest\.com|tiktok\.com|youtu\.be|youtube\.com)/i.test(url || "");
}

function socialFallbackData(url) {
  return {
    title: /instagram\.com/i.test(url || "") ? "Instagram Video" : "Social Media Video",
    thumbnail: "/assets/favorite-web-logo.png",
    videos: [{ url: null, label: "Best Video + Audio (Server Download)", hasAudio: true, ext: "mp4", vcodec: "H.264" }],
    audios: [],
    _server_download: true,
    normalized_url: normalizeClientUrl(url),
  };
}

function normalizeClientUrl(url) {
  try {
    var u = new URL(url.indexOf("http") === 0 ? url : "https://" + url);
    if (u.hostname === "l.instagram.com" && u.searchParams.get("u")) {
      u = new URL(u.searchParams.get("u"));
    }
    if (/instagram\.com$/i.test(u.hostname)) {
      var m = u.pathname.match(/^\/(reels?|p|tv)\/([A-Za-z0-9_-]+)/);
      if (m) {
        var mediaType = m[1] === "reels" ? "reel" : m[1];
        return "https://www.instagram.com/" + mediaType + "/" + m[2] + "/";
      }
    }
    return u.href;
  } catch {
    return url;
  }
}

function normalizeItem(data, inputUrl, index) {
  const videos = data.videos || (data.video ? [{ url: data.video, label: "Best video", hasAudio: true }] : data._server_download ? [{ url: null, label: "Best Video + Audio (Server Download)", hasAudio: true, ext: "mp4", vcodec: "H.264" }] : []);
  const audios = data.audios || (data.audio ? [{ url: data.audio, label: "Best audio" }] : []);
  const downloadUrl = data.normalized_url || inputUrl;
  const options = [
    ...videos.map(function(item) { return { ...item, type: "Video" }; }),
    ...audios.map(function(item) { return { ...item, type: "Audio" }; }),
  ];
  return { ...data, inputUrl, downloadUrl, index, options, serverDownload: data._server_download === true };
}

// ===================================================================
// Helpers
// ===================================================================
function formatSize(bytes) {
  if (!bytes && bytes !== 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let size = Number(bytes);
  let i = 0;
  while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
  return size.toFixed(i ? 1 : 0) + " " + units[i];
}

function escapeHtml(v) {
  var s = String(v || "");
  var map = { "&": "amp", "<": "lt", ">": "gt", '"': "quot", "'": "#039" };
  return s.replace(/[&<>"']/g, function(m) { return "&" + map[m] + ";"; });
}

function optionText(item) {
  const notes = [
    item.hasAudio === false ? "audio auto-merge" : "",
    item.filesize ? formatSize(item.filesize) + (item.filesizeApprox ? " approx" : "") : "",
  ].filter(Boolean);
  return item.type + " - " + item.label + (notes.length ? " (" + notes.join(", ") + ")" : "");
}

function getShortTitle(title) {
  if (!title) return "video";
  return title.length > 40 ? title.slice(0, 40) + "\u2026" : title;
}

function formatDuration(item) {
  if (item.duration_string) return item.duration_string;

  var seconds = Number(item.duration);
  if (!Number.isFinite(seconds) || seconds <= 0) return "";

  seconds = Math.round(seconds);
  var h = Math.floor(seconds / 3600);
  var m = Math.floor((seconds % 3600) / 60);
  var s = seconds % 60;

  if (h > 0) {
    return h + ":" + String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
  }
  return m + ":" + String(s).padStart(2, "0");
}

function parseFilenameFromDisposition(disposition) {
  if (!disposition) return null;
  // Try filename*=UTF-8''encoded_name (RFC 5987) first - highest priority
  var starMatch = disposition.match(/filename\*\s*=\s*UTF-8''(.+)/i);
  if (starMatch) {
    try { return decodeURIComponent(starMatch[1].replace(/["';].*/,'').trim()); }
    catch(e) { /* fall through */ }
  }
  // Try filename="some file.mp4" (quoted, may contain spaces)
  var quotedMatch = disposition.match(/filename\s*=\s*"([^"]+)"/i);
  if (quotedMatch) return quotedMatch[1].trim();
  // Try filename=somefile.mp4 (unquoted, stops at semicolon)
  var bareMatch = disposition.match(/filename\s*=\s*([^;\s]+)/i);
  if (bareMatch) return bareMatch[1].replace(/["']/g,'').trim();
  return null;
}

function getKnownTotal(option) {
  var size = Number(option && option.filesize);
  return Number.isFinite(size) && size > 0 ? size : 0;
}

function getHeaderSize(headers, name) {
  var value = parseInt(headers.get(name), 10);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function getProgressPct(loaded, total) {
  if (!total || total <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((loaded / total) * 100)));
}

// ===================================================================
// Render results
// ===================================================================
function renderResults(items) {
  const valid = items.filter(function(i) { return !i.error; });
  const failed = items.length - valid.length;

  var globalOptsHtml = buildGlobalQualityOptions(items);

  document.getElementById("result").innerHTML =
    '<div class="result-toolbar">' +
      '<div><strong>' + valid.length + '</strong> ready' +
      (failed ? ' <span class="fail-count">\u00b7 ' + failed + ' failed</span>' : "") + '</div>' +
      '<div class="global-quality-wrap">' +
        '<label for="globalQuality">Quality</label>' +
        '<select id="globalQuality" onchange="applyGlobalQuality(this.value)">' + globalOptsHtml + '</select>' +
      '</div>' +
      '<button class="compact" onclick="downloadAllSelected(\'fast\')"' + (valid.length ? "" : " disabled") + '>\u2b07 Fast download all</button>' +
      '<button class="compact" onclick="downloadAllSelected(\'convert\')"' + (valid.length ? "" : " disabled") + '>Convert and download all</button>' +
    '</div>' +
    '<div class="results-list">' +
      items.map(renderCard).join("") +
    '</div>';
}

function buildGlobalQualityOptions(items) {
  var seen = {};
  var list = [];

  items.forEach(function(item) {
    if (item.error) return;
    item.options.forEach(function(opt) {
      var key = getQualityKey(opt);
      if (key && !seen[key]) {
        seen[key] = true;
        list.push({ key: key, label: getQualityLabel(opt), priority: opt.type === "Video" ? (opt.quality || 0) : -1 });
      }
    });
  });

  // Sort: best first by quality descending, audio at the end
  list.sort(function(a, b) { return b.priority - a.priority; });

  var html = '<option value="">Default (per-video)</option>';
  list.forEach(function(item) {
    html += '<option value="' + item.key + '">' + escapeHtml(item.label) + '</option>';
  });
  return html;
}

function getQualityKey(opt) {
  if (opt.type === "Video") {
    return "v-" + (opt.quality || 0);
  }
  if (opt.type === "Audio") {
    return "a-" + (opt.bitrate || 0);
  }
  return "";
}

function getQualityLabel(opt) {
  if (opt.type === "Video") {
    var h = opt.quality || 0;
    return h > 0 ? h + "p" : "Video";
  }
  if (opt.type === "Audio") {
    var br = opt.bitrate || 0;
    return br > 0 ? br + " kbps" : "Audio";
  }
  return opt.label || "Unknown";
}

function applyGlobalQuality(key) {
  if (!key) return;

  loadedItems.forEach(function(item) {
    if (item.error) return;
    var select = document.getElementById("quality-" + item.index);
    if (!select) return;

    var bestMatchIdx = -1;
    for (var i = 0; i < item.options.length; i++) {
      var opt = item.options[i];
      if (getQualityKey(opt) === key) {
        bestMatchIdx = i;
        break;
      }
    }

    if (bestMatchIdx >= 0) {
      select.value = String(bestMatchIdx);
    }
  });
}

function renderCard(item) {
  if (item.error) {
    return '<section class="result-card failed-card"><div><p class="error">\u26a0 ' + escapeHtml(item.error) + '</p><small>' + escapeHtml(item.inputUrl) + '</small></div></section>';
  }

  const opts = item.options.map(function(opt, oi) {
    return '<option value="' + oi + '">' + escapeHtml(optionText(opt)) + '</option>';
  }).join("");

  var existingDl = downloadStates[item.index];
  var progressHtml = "";
  if (existingDl) {
    progressHtml = buildProgressHtml(item.index);
  }

  var isDownloading = existingDl && existingDl.active;
  var duration = formatDuration(item);

  return '<section class="result-card" id="card-' + item.index + '">' +
    '<div class="media-head">' +
      (item.thumbnail ? '<img src="' + item.thumbnail + '" alt="" loading="lazy">' : "") +
      '<div class="media-info"><h3>' + escapeHtml(item.title || "Available downloads") + '</h3>' +
        '<div class="media-meta">' +
          '<small>' + escapeHtml(item.inputUrl) + '</small>' +
          (duration ? '<small class="duration-badge">\u23f1 ' + escapeHtml(duration) + '</small>' : "") +
        '</div></div>' +
    '</div>' +
    '<div class="quality-row">' +
      '<label for="quality-' + item.index + '">Quality</label>' +
      '<select id="quality-' + item.index + '">' + (opts || '<option value="">No formats</option>') + '</select>' +
      '<button class="fast-download-btn" id="fastbtn-' + item.index + '" onclick="startDownload(' + item.index + ', \'fast\')"' +
        (opts ? "" : " disabled") + (isDownloading ? ' disabled' : '') + '>\u2b07 Fast download</button>' +
      '<button class="convert-download-btn" id="convertbtn-' + item.index + '" onclick="startDownload(' + item.index + ', \'convert\')"' +
        (opts ? "" : " disabled") + (isDownloading ? ' disabled' : '') + '>Convert & download</button>' +
    '</div>' +
    '<div id="progress-' + item.index + '" class="download-progress-section">' + progressHtml + '</div>' +
  '</section>';
}

// ===================================================================
// Start download
// ===================================================================
function startDownload(itemIndex, mode) {
  mode = mode === "convert" ? "convert" : "fast";
  var item = loadedItems.find(function(e) { return e.index === itemIndex; });
  if (!item) return;

  var select = document.getElementById("quality-" + itemIndex);
  var option = item.options[Number(select.value)];
  if (!option) return;

  // Prevent duplicate
  var state = downloadStates[itemIndex];
  if (state && state.active) return;

  setDownloadButtons(itemIndex, true);

  var displayTitle = getShortTitle(item.title || "video");
  var fullTitle = (item.title || "video");
  var modeLabel = mode === "convert" ? "Convert" : "Fast";
  var label = displayTitle + " \u2013 " + modeLabel + " \u2013 " + optionText(option);
  var id = itemIndex + "-" + Date.now();
  var inputUrl = item.inputUrl || "";
  var initialTotal = getKnownTotal(option);

  downloadStates[itemIndex] = {
    active: true,
    items: [{
      id: id,
      label: label,
      progress: {
        pct: 0,
        loaded: 0,
        total: initialTotal,
        status: "downloading",
        totalIsExact: false
      }
    }],
    progress: { pct: 0, loaded: 0, total: initialTotal }
  };

  var container = document.getElementById("progress-" + itemIndex);
  if (container) {
    container.innerHTML = buildProgressHtml(itemIndex);
  }

  if (mode === "convert" || item.serverDownload || !option.url || option.type === "Video") {
    serverSideDownload(itemIndex, id, item.downloadUrl || item.inputUrl, fullTitle, option, mode);
  } else if (option.url) {
    // Determine extension from option
    var ext = (option.ext || "mp4");
    if (option.type === "Audio" && ext === "mp4") ext = "m4a";
    var filenameWithTitle = fullTitle + "." + ext;
    if (option.hasAudio === false && item.audios && item.audios.length > 0) {
      // Video-only formats need server-side merge, but keep the selected quality.
      serverSideDownload(itemIndex, id, item.downloadUrl || item.inputUrl, fullTitle, option, mode);
    } else {
      // Has audio already or audio only: proxy download directly
      fetchDownload(itemIndex, id, "/download/proxy?url=" + encodeURIComponent(option.url), filenameWithTitle, getKnownTotal(option));
    }
  } else {
    serverSideDownload(itemIndex, id, item.downloadUrl || item.inputUrl, fullTitle, option, mode);
  }
}

// ===================================================================
// Server-side download (most reliable for Instagram/Facebook)
// Uses yt-dlp on the server to download and stream the complete file
// ===================================================================
async function serverSideDownload(itemIndex, id, inputUrl, title, option, mode) {
  var shouldConvert = mode === "convert";
  updateProgressCustom(
    itemIndex,
    id,
    0,
    shouldConvert ? "Preparing converted download..." : "Preparing fast download...",
    "downloading"
  );
  try {
    var params = new URLSearchParams();
    params.set("url", inputUrl);
    if (option && option.formatId) params.set("format", option.formatId);
    if (option && option.type) params.set("type", option.type.toLowerCase());
    if (option && option.hasAudio) params.set("hasAudio", "1");
    if (shouldConvert) params.set("compat", "1");

    var response = await fetch("/download/start-download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(params))
    });
    var startData = await response.json().catch(function() { return {}; });
    if (!response.ok || !startData.jobId) {
      updateProgress(itemIndex, id, 0, 0, 0, "error");
      finishDownload(itemIndex);
      return;
    }

    var ready = await waitForServerJob(itemIndex, id, startData.jobId);
    if (!ready) {
      updateProgress(itemIndex, id, 0, 0, 0, "error");
      finishDownload(itemIndex);
      return;
    }

    updateProgressCustom(itemIndex, id, 0, "Starting browser download...", "downloading");
    fetchDownload(
      itemIndex,
      id,
      "/download/job-file/" + encodeURIComponent(startData.jobId),
      ready.filename || (title + ".mp4"),
      ready.size || 0
    );
  } catch (err) {
    updateProgress(itemIndex, id, 0, 0, 0, "error");
    finishDownload(itemIndex);
  }
}

async function waitForServerJob(itemIndex, id, jobId) {
  var delay = 1200;
  while (true) {
    await new Promise(function(resolve) { setTimeout(resolve, delay); });
    var response = await fetch("/download/job-status/" + encodeURIComponent(jobId), { cache: "no-store" });
    var data = await response.json().catch(function() { return {}; });

    if (!response.ok || data.status === "error") {
      updateProgressCustom(itemIndex, id, 0, data.error || "Download failed", "error");
      return null;
    }

    var pct = Number(data.pct || 0);
    var total = Number(data.total || data.size || 0);
    var loaded = Number(data.downloaded || 0);
    var statusText = data.phase || "Preparing download...";
    if (loaded && total) {
      statusText += " " + formatSize(loaded) + " / " + formatSize(total);
    }
    updateProgressCustom(itemIndex, id, pct, statusText, "downloading");

    if (data.status === "ready") {
      return data;
    }

    delay = Math.min(2500, delay + 150);
  }
}

function downloadAllSelected(mode) {
  mode = mode === "convert" ? "convert" : "fast";
  loadedItems.filter(function(i) { return !i.error; }).forEach(function(item) {
    var select = document.getElementById("quality-" + item.index);
    var option = item.options[Number(select.value)];
    if (option) {
      startDownload(item.index, mode);
    }
  });
}

// ===================================================================
// Merged URL download (uses yt-dlp on server for proper video+audio)
// ===================================================================
async function mergedUrlDownload(itemIndex, id, inputUrl, title, filename) {
  updateProgressCustom(itemIndex, id, 0, "Getting merged video+audio from server...", "downloading");
  try {
    var resp = await fetch("/download/merged-url?url=" + encodeURIComponent(inputUrl));
    var data = await resp.json();
    if (!resp.ok || !data.url) {
      updateProgress(itemIndex, id, 0, 0, 0, "error");
      finishDownload(itemIndex);
      return;
    }
    // Download the merged URL through our proxy
    fetchDownload(itemIndex, id, "/download/proxy?url=" + encodeURIComponent(data.url), filename || (title + ".mp4"), 0);
  } catch (err) {
    updateProgress(itemIndex, id, 0, 0, 0, "error");
    finishDownload(itemIndex);
  }
}

// ===================================================================
// Proxy download (Fetch API + ReadableStream)
// ===================================================================
async function fetchDownload(itemIndex, id, proxyUrl, filename, expectedTotal) {
  try {
    var response = await fetch(proxyUrl);
    if (!response.ok) {
      updateProgress(itemIndex, id, 0, 0, 0, "error");
      finishDownload(itemIndex);
      return;
    }

    var headerTotal = getHeaderSize(response.headers, "Content-Length");
    var total = headerTotal || expectedTotal || 0;
    var reader = response.body.getReader();
    var chunks = [];
    var loaded = 0;

    while (true) {
      var result = await reader.read();
      if (result.done) break;
      var chunk = result.value;
      chunks.push(chunk);
      loaded += chunk.length;
      var shownTotal = (!headerTotal && total > 0 && loaded > total) ? 0 : total;
      var pct = getProgressPct(loaded, shownTotal);
      updateProgress(itemIndex, id, pct, loaded, shownTotal, "downloading", !!headerTotal);
    }

    var blob = new Blob(chunks, { type: response.headers.get("Content-Type") || "application/octet-stream" });
    updateProgress(itemIndex, id, 100, blob.size, blob.size > 0 ? blob.size : 0, "done", true);
    triggerBlobDownload(blob, filename || "download");
    finishDownload(itemIndex);
  } catch (err) {
    updateProgress(itemIndex, id, 0, 0, 0, "error");
    finishDownload(itemIndex);
  }
}

// ===================================================================
// Progress UI
// ===================================================================
function updateProgress(itemIndex, id, pct, loaded, total, status, totalIsExact) {
  var state = downloadStates[itemIndex];
  if (!state) return;
  var item = state.items.find(function(i) { return i.id === id; });
  if (item) {
    item.progress = {
      pct: pct,
      loaded: loaded,
      total: total,
      status: status,
      totalIsExact: !!totalIsExact
    };
  }
  var container = document.getElementById("progress-" + itemIndex);
  if (container) container.innerHTML = buildProgressHtml(itemIndex);
}

function updateProgressCustom(itemIndex, id, pct, statusText, status) {
  var state = downloadStates[itemIndex];
  if (!state) return;
  var item = state.items.find(function(i) { return i.id === id; });
  if (item) {
    item.progress = { pct: pct, loaded: 0, total: 0, status: status, statusText: statusText };
  }
  var container = document.getElementById("progress-" + itemIndex);
  if (container) container.innerHTML = buildProgressHtml(itemIndex);
}

function buildProgressHtml(itemIndex) {
  var state = downloadStates[itemIndex];
  if (!state || !state.items.length) return "";

  var rows = "";
  state.items.forEach(function(i) {
    var p = i.progress;
    var pct = Math.max(0, Math.min(100, p.pct || 0));
    var loadedStr = p.statusText || (p.total ? formatSize(p.loaded) + " / " + formatSize(p.total) : formatSize(p.loaded));
    if (p.total && !p.totalIsExact && !p.statusText) loadedStr += " approx";
    var isIndeterminate = p.status === "downloading" && !p.total && !pct;

    var statusIcon = "";
    var statusClass = "progress-status";
    var statusText = "";
    if (p.status === "done") { statusIcon = "\u2705 "; statusClass += " done"; statusText = "Complete"; }
    else if (p.status === "error") { statusIcon = "\u274c "; statusClass += " error"; statusText = "Failed"; }
    else { statusIcon = "\u2b07 "; statusText = ""; }

    rows +=
      '<div class="progress-item">' +
        '<span class="progress-label">' + statusIcon + escapeHtml(i.label) + '</span>' +
        '<div class="progress-track' + (isIndeterminate ? ' indeterminate' : '') + '"><div class="progress-fill" style="width:' + pct + '%"></div></div>' +
        '<span class="progress-pct">' + (isIndeterminate ? "--" : pct + "%") + '</span>' +
        '<span class="progress-size">' + escapeHtml(loadedStr) + '</span>' +
        '<span class="' + statusClass + '">' + statusText + '</span>' +
      '</div>';
  });
  return rows;
}

function finishDownload(itemIndex) {
  var state = downloadStates[itemIndex];
  if (state) state.active = false;
  setDownloadButtons(itemIndex, false);
}

function setDownloadButtons(itemIndex, disabled) {
  var fastBtn = document.getElementById("fastbtn-" + itemIndex);
  var convertBtn = document.getElementById("convertbtn-" + itemIndex);
  if (fastBtn) fastBtn.disabled = disabled;
  if (convertBtn) convertBtn.disabled = disabled;
}

// ===================================================================
// Trigger file download from blob
// ===================================================================
function triggerBlobDownload(blob, filename) {
  var url = URL.createObjectURL(blob);
  var a = document.createElement("a");
  a.href = url;
  a.download = filename || "download";
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(function() { URL.revokeObjectURL(url); }, 5000);
}

// ===================================================================
// Backward compat
// ===================================================================
function downloadSelected(itemIndex) {
  startDownload(itemIndex, "fast");
}
