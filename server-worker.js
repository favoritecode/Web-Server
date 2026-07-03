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
const OFFLINE_BACKENDS = [PRIMARY, BACKUP];
const HLS_TIMEOUT = 6500;
const WORKER_OFFLINE_SEGMENT_PATH = "/__offline/offline.ts";
const OFFLINE_BACKEND_PLAYLIST = "/offline/index.m3u8";
const AUTH_PATHS = ["/login", "/logout", "/login/callback"];
const LONG_RUNNING_PATHS = [
  "/api/analytics/",
  "/ocr/extract",
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
      return true;
    }
  } catch (e) {}

  // Backward-compatible check for a backend that has not received the new
  // health route yet. Cloudflare error pages will not pass this JSON test.
  return hasJsonUserEndpoint(target, publicHost);
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

  if (isHlsMediaPath(incomingUrl.pathname)) {
    rewritten.headers.set("Cache-Control", "no-store");
    rewritten.headers.set("Access-Control-Allow-Origin", "*");
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

  for (const target of STREAM_BACKENDS) {
    try {
      const live = await fetchHlsPlaylist(
        request,
        target,
        liveBackendPlaylist(streamName),
        livePublicPrefix(streamName)
      );
      if (live) {
        return live;
      }
    } catch (e) {
      // Try the next backend, then fall back to the offline slate.
    }
  }

  for (const target of OFFLINE_BACKENDS) {
    try {
      const offline = await fetchHlsPlaylist(request, target, OFFLINE_BACKEND_PLAYLIST, "/offline");
      if (offline) {
        return offline;
      }
    } catch (e) {}
  }

  return workerOfflinePlaylist(incomingUrl.origin);
}

async function proxyWithFailover(request) {
  let lastResponse = null;
  const url = new URL(request.url);
  const targets = isHlsMediaPath(url.pathname) ? STREAM_BACKENDS : (isOcrPath(url.pathname) ? OCR_BACKENDS : BACKENDS);

  for (const target of targets) {
    try {
      const response = await proxyTo(request.clone(), target);

      if (isHlsMediaPath(url.pathname) && shouldTryNextHlsBackend(response)) {
        lastResponse = response;
        continue;
      }

      if (response.status < 500) {
        return response;
      }

      lastResponse = response;
    } catch (e) {}
  }

  if (isOcrPath(url.pathname)) {
    return new Response(JSON.stringify({ error: "OCR PC servers are unavailable" }), {
      status: 503,
      headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "X-FavoriteWeb-Worker": "server-failover", "X-FavoriteWeb-Target": "none" }
    });
  }

  return lastResponse || new Response("Server unavailable", { status: 503 });
}

async function proxyAuthWithFailover(request) {
  const url = new URL(request.url);

  for (const target of BACKENDS) {
    if (!(await isHealthyBackend(target, url.host))) {
      continue;
    }

    try {
      const response = await proxyTo(request.clone(), target);

      if (response.status >= 500) {
        continue;
      }

      if (!hasCorrectGoogleRedirect(response, url.origin)) {
        continue;
      }

      return response;
    } catch (e) {}
  }

  return new Response("Login server unavailable", { status: 503 });
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const streamName = getStreamNameFromPlaylistPath(url.pathname);

    if (url.pathname === WORKER_OFFLINE_SEGMENT_PATH) {
      return workerOfflineSegment();
    }

    if (streamName) {
      return proxyLivePlaylist(request, streamName);
    }

    if (isAuthPath(url.pathname)) {
      return proxyAuthWithFailover(request);
    }

    return proxyWithFailover(request);
  }
};
