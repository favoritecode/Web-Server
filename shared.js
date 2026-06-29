// ============ SHARED NAVBAR & FOOTER ============

// Current page active state
const NAV_ITEMS = [
  { href: "/", label: "Home" },
  { href: "/download", label: "Download" },
  { href: "/upload", label: "Cloud Drive" },
  { href: "/ytplayer/", label: "YT Stream" },
  { href: "/ocr", label: "OCR" },
  { href: "/analytics", label: "Web Analyzer" },
];

function getCurrentPage() {
  const path = window.location.pathname;
  if (path === "/" || path === "") return "/";
  for (const item of NAV_ITEMS) {
    if (path.startsWith(item.href) && item.href !== "/") return item.href;
  }
  return "/";
}

function buildNavbar(user) {
  const current = getCurrentPage();
  let linksHtml = "";

  for (const item of NAV_ITEMS) {
    const active = current === item.href ? ' class="active"' : "";
    const href = item.href === "/upload" && !(user && user.logged_in) ? "/login" : item.href;
    linksHtml += `<a href="${href}"${active}>${item.label}</a>`;
  }

  if (user && user.logged_in) {
    const avatar = user.picture
      ? `<img src="${escapeHtml(user.picture)}" class="user-avatar" alt="">`
      : "";
    linksHtml +=
      `<a href="/upload" class="login-btn" style="display:inline-flex;align-items:center;gap:4px">${avatar}${escapeHtml(user.name || "Account")}</a>` +
      `<a href="/logout" class="logout-btn">Logout</a>`;
  } else {
    linksHtml += `<a href="/login" class="login-btn">Login</a>`;
  }

  return `
<nav class="navbar">
  <a href="https://favoriteweb.net/" class="logo"><img src="/assets/favorite-web-logo.png" alt="Favorite Web"><span>FavoriteWeb</span></a>
  <div class="nav-links">${linksHtml}</div>
</nav>`;
}

function buildFooter() {
  return `
<footer class="site-footer">
  <p>Copyright © <a href="https://favoriteweb.net/">Favorite Web</a> All Right Reserved</p>
</footer>`;
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&" + "amp;")
    .replace(/</g, "&" + "lt;")
    .replace(/>/g, "&" + "gt;")
    .replace(/"/g, "&" + "quot;")
    .replace(/'/g, "&" + "#039;");
}

// Inject navbar/footer into page
async function initSharedLayout() {
  // Fetch user state
  let user = { logged_in: false };
  try {
    const res = await fetch("/api/user");
    if (res.ok) user = await res.json();
  } catch (e) {}

  // Build and inject navbar
  const navbarHtml = buildNavbar(user);
  const footerHtml = buildFooter();

  // Insert at top of body
  document.body.insertAdjacentHTML("afterbegin", navbarHtml);

  // Insert at bottom of body
  document.body.insertAdjacentHTML("beforeend", footerHtml);

  // Wrap existing body content in main-content div (if not already)
  const existingContent = document.querySelector(".app-shell, .main-content");
  if (!existingContent) {
    const children = Array.from(document.body.children);
    // Find all elements between nav and footer
    const nav = document.querySelector(".navbar");
    const footer = document.querySelector(".site-footer");
    const toWrap = [];
    let foundNav = false;
    for (const child of children) {
      if (child === nav) { foundNav = true; continue; }
      if (child === footer) continue;
      if (foundNav) toWrap.push(child);
    }
    if (toWrap.length > 0) {
      const wrapper = document.createElement("div");
      wrapper.className = "main-content";
      for (const el of toWrap) wrapper.appendChild(el);
      // Re-insert after nav
      nav.insertAdjacentElement("afterend", wrapper);
    }
  }
}

// Run on DOM ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initSharedLayout);
} else {
  initSharedLayout();
}
