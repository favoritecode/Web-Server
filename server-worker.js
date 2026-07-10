import { OFFLINE_SEGMENT_BASE64 } from "./offline-segment.js";

// ============================================
// server.favoriteweb.net - Auto Failover Worker
// Keeps the public domain in the browser while proxying PC1/PC2.
// ============================================

const PRIMARY = "https://khan.favoriteweb.net";
const BACKUP = "https://host.favoriteweb.net";
const RENDER_BACKUP = "https://favoriteweb-backup.onrender.com";
const TIMEOUT = 3000;
const HEALTH_TIMEOUT = 2000;
const BACKENDS = [PRIMARY, BACKUP, RENDER_BACKUP];
const STREAM_BACKENDS = [PRIMARY, BACKUP];
const OCR_BACKENDS = [PRIMARY, BACKUP];
const PC_TOOL_BACKENDS = [PRIMARY, BACKUP];
const OFFLINE_BACKENDS = [PRIMARY, BACKUP];
const HLS_TIMEOUT = 6500;
const WORKER_OFFLINE_SEGMENT_PATH = "/__offline/offline.ts";
const OFFLINE_BACKEND_PLAYLIST = "/offline/index.m3u8";
const STICKY_BACKEND_COOKIE = "fw_backend";
const STICKY_BACKEND_MAX_AGE = 7 * 24 * 60 * 60;
const RENDER_STICKY_MAX_AGE = 5 * 60;
const STATIC_CACHE_MAX_AGE = 5 * 60;
const HLS_SEGMENT_CACHE_MAX_AGE = 20;
const FAILED_BACKEND_COOLDOWN_MS = 20 * 1000;
const backendCooldownUntil = new Map();
const AUTH_PATHS = ["/login", "/logout", "/login/callback"];
const LONG_RUNNING_PATHS = [
  "/api/analytics/",
  "/ocr/extract",
  "/file-converter/convert",
  "/remove-bg/process",
  "/article-generate/generate",
  "/api/drive/files",
  "/drive/open/",
  "/drive/download/",
  "/drive/media",
  "/drive/save",
  "/download/api",
  "/download/proxy",
  "/download/server-download",
  "/ytplayer/stream/",
  "/ytplayer/play/",
  "/open/",
  "/stream/",
  "/file/",
  "/live.m3u8",
  "/live/",
  "/offline/"
];

function buildHeaders(request, publicHost, targetHost) {
  const headers = new Headers(request.headers);

  headers.set("X-Forwarded-Host", publicHost);
  headers.set("X-Forwarded-Proto", "https");
  headers.set("X-Public-Host", publicHost);
  headers.set("X-Public-Proto", "https");
  headers.set("X-Real-Host", publicHost);

  // Cloudflare will set the real Host from the fetch URL. Removing the
  // incoming host avoids sending server.favoriteweb.net to a PC tunnel.
  headers.delete("Host");
  headers.delete("host");

  headers.set("X-Backend-Host", targetHost);

  return headers;
}

function rewriteLocation(location, publicOrigin) {
  if (!location) {
    return location;
  }

  if (location.startsWith(PRIMARY)) {
    return publicOrigin + location.slice(PRIMARY.length);
  }

  if (location.startsWith(BACKUP)) {
    return publicOrigin + location.slice(BACKUP.length);
  }

  if (location.startsWith(RENDER_BACKUP)) {
    return publicOrigin + location.slice(RENDER_BACKUP.length);
  }

  return location;
}

function isAuthPath(pathname) {
  return AUTH_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`));
}

function isLongRunningPath(pathname) {
  if (getStreamNameFromPlaylistPath(pathname) || isHlsMediaPath(pathname)) {
    return true;
  }

  return LONG_RUNNING_PATHS.some((path) => pathname === path || pathname.startsWith(path));
}

function isOcrPath(pathname) {
  return pathname === "/ocr" || pathname === "/ocr/" || pathname === "/ocr/extract" || pathname === "/ocr/health";
}

function isDriveFilePath(pathname) {
  return pathname === "/api/drive/files" || pathname === "/drive/media" || pathname === "/drive/save" || pathname.startsWith("/drive/open/") || pathname.startsWith("/drive/download/");
}

function isRemoveBgPath(pathname) {
  return pathname === "/remove-bg/process";
}

function isArticleGeneratePath(pathname) {
  return pathname === "/article-generate/generate";
}

function isPcToolPath(pathname) {
  return isOcrPath(pathname) || pathname === "/file-converter/convert" || isRemoveBgPath(pathname) || isArticleGeneratePath(pathname) || isDriveFilePath(pathname);
}

function isAdminUserUpdatePath(pathname) {
  return pathname === "/api/admin/users/update";
}

function isStaticAssetPath(pathname) {
  return pathname.startsWith("/assets/") || pathname === "/shared.css" || pathname === "/shared.js" || pathname === "/favicon.ico";
}

function isHlsSegmentPath(pathname) {
  return /^\/live[0-9A-Za-z_-]*\/.*\.(ts|m4s|aac|mp4)$/i.test(pathname) || /^\/offline\/.*\.(ts|m4s|aac|mp4)$/i.test(pathname);
}

function parseCookies(header) {
  const cookies = {};
  (header || "").split(";").forEach((part) => {
    const index = part.indexOf("=");
    if (index === -1) {
      return;
    }
    const name = part.slice(0, index).trim();
    const value = part.slice(index + 1).trim();
    if (name) {
      try {
        cookies[name] = decodeURIComponent(value);
      } catch (e) {
        cookies[name] = value;
      }
    }
  });
  return cookies;
}

function targetHost(target) {
  return new URL(target).host;
}

function stickyTarget(request, targets) {
  const cookies = parseCookies(request.headers.get("Cookie") || "");
  const stickyHost = cookies[STICKY_BACKEND_COOKIE] || "";
  return targets.find((target) => targetHost(target) === stickyHost) || null;
}

function orderedTargets(request, targets) {
  const sticky = stickyTarget(request, targets);
  if (!sticky) {
    return targets;
  }
  return [sticky, ...targets.filter((target) => target !== sticky)];
}

function stickyBackendCookie(target) {
  const host = targetHost(target);
  const maxAge = host === targetHost(RENDER_BACKUP) ? RENDER_STICKY_MAX_AGE : STICKY_BACKEND_MAX_AGE;
  return `${STICKY_BACKEND_COOKIE}=${encodeURIComponent(host)}; Path=/; Max-Age=${maxAge}; Secure; HttpOnly; SameSite=Lax`;
}

function isBackendCoolingDown(target) {
  const host = targetHost(target);
  const until = backendCooldownUntil.get(host) || 0;
  if (until <= Date.now()) {
    backendCooldownUntil.delete(host);
    return false;
  }
  return true;
}

function markBackendUnhealthy(target) {
  backendCooldownUntil.set(targetHost(target), Date.now() + FAILED_BACKEND_COOLDOWN_MS);
}

function markBackendHealthy(target) {
  backendCooldownUntil.delete(targetHost(target));
}

function availableTargets(request, targets) {
  const ordered = orderedTargets(request, targets);
  const available = ordered.filter((target) => !isBackendCoolingDown(target));
  return available.length ? available : ordered;
}

async function cacheFirst(request, ctx, maxAge, fetcher) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return fetcher();
  }

  const cache = caches.default;
  const cacheKey = new Request(request.url, { method: "GET" });
  const cached = await cache.match(cacheKey);
  if (cached) {
    const headers = new Headers(cached.headers);
    headers.set("X-FavoriteWeb-Cache", "hit");
    return new Response(cached.body, { status: cached.status, statusText: cached.statusText, headers });
  }

  const response = await fetcher();
  if (!response || !response.ok) {
    return response;
  }

  const headers = new Headers(response.headers);
  headers.delete("Set-Cookie");
  headers.delete("set-cookie");
  headers.set("Cache-Control", `public, max-age=${maxAge}`);
  const cacheable = new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  if (ctx && ctx.waitUntil) {
    ctx.waitUntil(cache.put(cacheKey, cacheable.clone()));
  }
  cacheable.headers.set("X-FavoriteWeb-Cache", "miss");
  return cacheable;
}
async function mirrorAdminUserUpdate(request, servedTargetHost) {
  const incomingUrl = new URL(request.url);

  await Promise.allSettled(
    PC_TOOL_BACKENDS.filter((target) => new URL(target).host !== servedTargetHost).map(async (target) => {
      const targetUrl = new URL(target);
      targetUrl.pathname = incomingUrl.pathname;
      targetUrl.search = incomingUrl.search;

      await fetch(targetUrl.toString(), {
        method: request.method,
        headers: buildHeaders(request, incomingUrl.host, targetUrl.host),
        body: request.clone().body,
        redirect: "manual",
        signal: AbortSignal.timeout(TIMEOUT)
      });
    })
  );
}

function isHlsMediaPath(pathname) {
  return /^\/live[0-9A-Za-z_-]*\//.test(pathname) || pathname.startsWith("/offline/");
}

function getStreamNameFromPlaylistPath(pathname) {
  const match = pathname.match(/^\/(live[0-9A-Za-z_-]*)\.m3u8$/);
  return match ? match[1] : null;
}

function liveBackendPlaylist(streamName) {
  return `/${streamName}/live/index.m3u8`;
}

function livePublicPrefix(streamName) {
  return `/${streamName}/live`;
}

function shouldTryNextHlsBackend(response) {
  return [401, 403, 404, 410].includes(response.status);
}

async function shouldTryNextDriveBackend(response) {
  if ([401, 403, 404, 410].includes(response.status)) {
    return true;
  }

  const contentType = response.headers.get("Content-Type") || "";
  if (!contentType.includes("application/json")) {
    return false;
  }

  try {
    const text = await response.clone().text();
    return /authentication error|login required|not allowed/i.test(text);
  } catch (e) {
    return false;
  }
}

function base64ToBytes(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);

  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }

  return bytes;
}

function workerOfflineSegment() {
  return new Response(base64ToBytes(OFFLINE_SEGMENT_BASE64), {
    status: 200,
    headers: {
      "Content-Type": "video/mp2t",
      "Cache-Control": "public, max-age=31536000",
      "Access-Control-Allow-Origin": "*"
    }
  });
}

function workerOfflinePlaylist(origin) {
  const sequence = Math.floor(Date.now() / 2000);
  const base = `${origin}${WORKER_OFFLINE_SEGMENT_PATH}`;
  const body = [
    "#EXTM3U",
    "#EXT-X-VERSION:3",
    "#EXT-X-TARGETDURATION:2",
    `#EXT-X-MEDIA-SEQUENCE:${sequence}`,
    "#EXT-X-ALLOW-CACHE:NO",
    "#EXTINF:2.0,",
    `${base}?seq=${sequence}`,
    "#EXTINF:2.0,",
    `${base}?seq=${sequence + 1}`,
    "#EXTINF:2.0,",
    `${base}?seq=${sequence + 2}`,
    ""
  ].join("\n");

  return new Response(body, {
    status: 200,
    headers: {
      "Content-Type": "application/vnd.apple.mpegurl",
      "Cache-Control": "no-store",
      "Access-Control-Allow-Origin": "*"
    }
  });
}

function hasCorrectGoogleRedirect(response, publicOrigin) {
  const location = response.headers.get("Location") || "";

  if (!location.includes("accounts.google.com")) {
    return true;
  }

  try {
    const googleUrl = new URL(location);
    const redirectUri = googleUrl.searchParams.get("redirect_uri") || "";
    return redirectUri.startsWith(`${publicOrigin}/login/callback`);
  } catch (e) {
    return false;
  }
}

async function hasJsonUserEndpoint(target, publicHost) {
  try {
    const response = await fetch(`${target}/api/user`, {
      method: "GET",
      headers: {
        "Accept": "application/json",
        "X-Public-Host": publicHost,
        "X-Public-Proto": "https"
      },
      redirect: "manual",
      signal: AbortSignal.timeout(HEALTH_TIMEOUT)
    });

    if (!response.ok) {
      return false;
    }

    const contentType = response.headers.get("Content-Type") || "";
    if (!contentType.includes("application/json")) {
      return false;
    }

    const data = await response.json();
    return typeof data.logged_in === "boolean";
  } catch (e) {
    return false;
  }
}

async function isHealthyBackend(target, publicHost) {
  if (isBackendCoolingDown(target)) {
    return false;
  }

  try {
    const response = await fetch(`${target}/__server_health`, {
      method: "GET",
      headers: {
        "X-Public-Host": publicHost,
        "X-Public-Proto": "https"
      },
      redirect: "manual",
      signal: AbortSignal.timeout(HEALTH_TIMEOUT)
    });

    if (response.status === 204 && response.headers.get("X-FavoriteWeb-Backend") === "ok") {
      markBackendHealthy(target);
      return true;
    }
  } catch (e) {}

  // Backward-compatible check for a backend that has not received the new
  // health route yet. Cloudflare error pages will not pass this JSON test.
  if (await hasJsonUserEndpoint(target, publicHost)) {
    markBackendHealthy(target);
    return true;
  }

  markBackendUnhealthy(target);
  return false;
}

async function pickHealthyBackend(publicHost) {
  for (const target of BACKENDS) {
    if (await isHealthyBackend(target, publicHost)) {
      return target;
    }
  }

  return null;
}

function rewriteResponse(response, publicOrigin) {
  const headers = new Headers(response.headers);
  const location = headers.get("Location");

  if (location) {
    headers.set("Location", rewriteLocation(location, publicOrigin));
  }

  // Flask is configured without a cookie Domain, but this removes any stale
  // backend domain attribute if one is added later.
  const setCookie = headers.get("Set-Cookie");
  if (setCookie) {
    headers.set(
      "Set-Cookie",
      setCookie.replace(/;\s*Domain=((khan|host)\.favoriteweb\.net|favoriteweb-backup\.onrender\.com)/gi, "")
    );
  }

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers
  });
}

async function proxyTo(request, target) {
  const incomingUrl = new URL(request.url);
  const targetUrl = new URL(target);
  targetUrl.pathname = incomingUrl.pathname;
  targetUrl.search = incomingUrl.search;

  const init = {
    method: request.method,
    headers: buildHeaders(request, incomingUrl.host, targetUrl.host),
    redirect: "manual"
  };

  if (!isLongRunningPath(incomingUrl.pathname)) {
    init.signal = AbortSignal.timeout(TIMEOUT);
  }

  if (!["GET", "HEAD"].includes(request.method)) {
    init.body = request.body;
  }

  const response = await fetch(targetUrl.toString(), init);
  const rewritten = rewriteResponse(response, incomingUrl.origin);

  rewritten.headers.set("X-FavoriteWeb-Worker", "server-failover");
  rewritten.headers.set("X-FavoriteWeb-Target", targetUrl.host);

  if (!isHlsMediaPath(incomingUrl.pathname) && !isStaticAssetPath(incomingUrl.pathname)) {
    rewritten.headers.append("Set-Cookie", stickyBackendCookie(target));
  }

  if (isHlsMediaPath(incomingUrl.pathname)) {
    rewritten.headers.set("Cache-Control", "no-store");
    rewritten.headers.set("Access-Control-Allow-Origin", "*");
  }

  if (isDriveFilePath(incomingUrl.pathname)) {
    rewritten.headers.set("Cache-Control", "no-store");
  }

  return rewritten;
}

function rewriteHlsPlaylist(text, publicPrefix) {
  return text
    .split("\n")
    .map((line) => {
      const trimmed = line.trim();

      if (!trimmed) {
        return line;
      }

      if (trimmed.startsWith("#")) {
        return line.replace(/URI="([^"]+)"/g, (match, uri) => {
          if (/^[a-z][a-z0-9+.-]*:\/\//i.test(uri) || uri.startsWith("/")) {
            return match;
          }

          return `URI="${publicPrefix}/${uri}"`;
        });
      }

      if (/^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) || trimmed.startsWith("/")) {
        return line;
      }

      return `${publicPrefix}/${trimmed}`;
    })
    .join("\n");
}

async function fetchHlsPlaylist(request, target, backendPath, publicPrefix) {
  const incomingUrl = new URL(request.url);
  const targetUrl = new URL(target);
  targetUrl.pathname = backendPath;
  targetUrl.search = incomingUrl.search;
  const absolutePublicPrefix = `${incomingUrl.origin}${publicPrefix}`;

  const response = await fetch(targetUrl.toString(), {
    method: "GET",
    headers: buildHeaders(request, incomingUrl.host, targetUrl.host),
    redirect: "follow",
    signal: AbortSignal.timeout(HLS_TIMEOUT)
  });

  if (!response.ok) {
    return null;
  }

  const body = rewriteHlsPlaylist(await response.text(), absolutePublicPrefix);
  return new Response(body, {
    status: 200,
    headers: {
      "Content-Type": "application/vnd.apple.mpegurl",
      "Cache-Control": "no-store",
      "Access-Control-Allow-Origin": "*"
    }
  });
}

async function proxyLivePlaylist(request, streamName) {
  const incomingUrl = new URL(request.url);

  for (const target of availableTargets(request, STREAM_BACKENDS)) {
    try {
      const live = await fetchHlsPlaylist(
        request,
        target,
        liveBackendPlaylist(streamName),
        livePublicPrefix(streamName)
      );
      if (live) {
        markBackendHealthy(target);
        return live;
      }
    } catch (e) {
      markBackendUnhealthy(target);
    }
  }

  for (const target of availableTargets(request, OFFLINE_BACKENDS)) {
    try {
      const offline = await fetchHlsPlaylist(request, target, OFFLINE_BACKEND_PLAYLIST, "/offline");
      if (offline) {
        markBackendHealthy(target);
        return offline;
      }
    } catch (e) {
      markBackendUnhealthy(target);
    }
  }

  return workerOfflinePlaylist(incomingUrl.origin);
}

async function proxyWithFailover(request) {
  let lastResponse = null;
  const url = new URL(request.url);
  const baseTargets = isHlsMediaPath(url.pathname) ? STREAM_BACKENDS : (isPcToolPath(url.pathname) ? PC_TOOL_BACKENDS : BACKENDS);
  const targets = availableTargets(request, baseTargets);

  for (const target of targets) {
    try {
      const response = await proxyTo(request.clone(), target);

      if (isHlsMediaPath(url.pathname) && shouldTryNextHlsBackend(response)) {
        lastResponse = response;
        continue;
      }

      if (isDriveFilePath(url.pathname) && await shouldTryNextDriveBackend(response)) {
        lastResponse = response;
        continue;
      }

      if (response.status < 500) {
        markBackendHealthy(target);
        return response;
      }

      if (isPcToolPath(url.pathname) && (response.headers.get("Content-Type") || "").includes("application/json")) {
        return response;
      }

      markBackendUnhealthy(target);
      lastResponse = response;
    } catch (e) {
      markBackendUnhealthy(target);
    }
  }

  if (isPcToolPath(url.pathname)) {
    return new Response(JSON.stringify({ error: isOcrPath(url.pathname) ? "OCR PC servers are unavailable" : (isDriveFilePath(url.pathname) ? "Drive PC servers are unavailable" : (isRemoveBgPath(url.pathname) ? "Remove BG PC servers are unavailable" : (isArticleGeneratePath(url.pathname) ? "Article Generate PC servers are unavailable" : "File converter PC servers are unavailable"))) }), {
      status: 503,
      headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "X-FavoriteWeb-Worker": "server-failover", "X-FavoriteWeb-Target": "none" }
    });
  }

  return lastResponse || new Response("Server unavailable", { status: 503 });
}

async function proxyAuthWithFailover(request) {
  const url = new URL(request.url);

  for (const target of availableTargets(request, BACKENDS)) {
    if (!(await isHealthyBackend(target, url.host))) {
      continue;
    }

    try {
      const response = await proxyTo(request.clone(), target);

      if (response.status >= 500) {
        markBackendUnhealthy(target);
        continue;
      }

      if (!hasCorrectGoogleRedirect(response, url.origin)) {
        continue;
      }

      markBackendHealthy(target);
      return response;
    } catch (e) {
      markBackendUnhealthy(target);
    }
  }

  return new Response("Login server unavailable", { status: 503 });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const streamName = getStreamNameFromPlaylistPath(url.pathname);

    if (url.pathname === WORKER_OFFLINE_SEGMENT_PATH) {
      return workerOfflineSegment();
    }

    if (isStaticAssetPath(url.pathname)) {
      return cacheFirst(request, ctx, STATIC_CACHE_MAX_AGE, () => proxyWithFailover(request));
    }

    if (isHlsSegmentPath(url.pathname)) {
      return cacheFirst(request, ctx, HLS_SEGMENT_CACHE_MAX_AGE, () => proxyWithFailover(request));
    }

    if (streamName) {
      return proxyLivePlaylist(request, streamName);
    }

    if (isAuthPath(url.pathname)) {
      return proxyAuthWithFailover(request);
    }

    if (isAdminUserUpdatePath(url.pathname) && request.method === "POST") {
      const mirrorRequest = request.clone();
      const response = await proxyWithFailover(request);
      const servedTargetHost = response.headers.get("X-FavoriteWeb-Target") || "";

      if (response.ok && servedTargetHost && ctx && ctx.waitUntil) {
        ctx.waitUntil(mirrorAdminUserUpdate(mirrorRequest, servedTargetHost));
      }

      return response;
    }

    return proxyWithFailover(request);
  }
};
