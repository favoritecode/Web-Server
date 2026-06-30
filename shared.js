// ============ SHARED NAVBAR & FOOTER ============

const NAV_ITEMS = [
  { href: "/", label: "Home" },
  { href: "/download", label: "Download" },
  { href: "/upload", label: "Cloud Drive", requiresAuth: true },
  { href: "/ytplayer/", label: "YT Stream" },
  { href: "/ocr", label: "OCR" },
  { href: "/analytics", label: "Web Analyzer" },
];

function getCurrentPage() {
  const path = window.location.pathname;
  if (path === "/" || path === "") return "/";
  for (const item of NAV_ITEMS) {
    if (!item.external && item.href !== "/" && path.startsWith(item.href)) return item.href;
  }
  return "/";
}

function resolveNavHref(item, user) {
  if (item.requiresAuth && !(user && user.logged_in)) return "/login";
  return item.href;
}

function buildNavLinks(user, className) {
  const current = getCurrentPage();
  return NAV_ITEMS.map((item) => {
    const active = !item.external && current === item.href ? " active" : "";
    const target = item.external ? ' target="_blank" rel="noopener"' : "";
    return `<a class="${className}${active}" href="${resolveNavHref(item, user)}"${target}>${escapeHtml(item.label)}</a>`;
  }).join("");
}

function avatarMarkup(user) {
  if (user && user.picture) {
    return `<img src="${escapeHtml(user.picture)}" class="fw-user-avatar" alt="">`;
  }
  return `<img src="/assets/favorite-web-logo.png" class="fw-user-avatar" alt="">`;
}

function buildAuthArea(user) {
  if (user && user.logged_in) {
    const name = escapeHtml(user.name || "FavoriteWeb User");
    const email = escapeHtml(user.email || "Signed in");
    return `
      <div class="fw-user-menu">
        <button class="fw-avatar-button" type="button" aria-label="Open account menu" aria-expanded="false">
          ${avatarMarkup(user)}
        </button>
        <div class="fw-user-dropdown" role="menu">
          <div class="fw-user-summary">
            ${avatarMarkup(user)}
            <div><strong>${name}</strong><span>${email}</span></div>
          </div>
          <a href="/profile" role="menuitem">View Profile</a>
          <a href="/dashboard" role="menuitem">Open Dashboard</a>
          <a href="/settings" role="menuitem">Settings</a>
          <a href="/logout" role="menuitem" class="danger">Logout</a>
        </div>
      </div>`;
  }
  return `<a href="/login" class="fw-login-button">Login</a>`;
}

function buildSearch(className) {
  return `
    <label class="${className}">
      <span aria-hidden="true"></span>
      <input class="fw-tool-search-input" type="search" placeholder="Search tools..." autocomplete="off" aria-label="Search tools">
    </label>`;
}

function buildNavbar(user) {
  return `
<header class="fw-nav-shell">
  <nav class="fw-navbar" aria-label="FavoriteWeb navigation">
    <button class="fw-menu-toggle" type="button" aria-label="Open menu" aria-expanded="false">
      <span></span><span></span><span></span>
    </button>
    <a href="https://favoriteweb.net/" class="fw-logo" aria-label="FavoriteWeb">
      <img src="/assets/favorite-web-logo.png" alt="Favorite Web">
      <span>FavoriteWeb</span>
    </a>
    <div class="fw-desktop-links">${buildNavLinks(user, "fw-nav-link")}</div>
    ${buildSearch("fw-search fw-desktop-search")}
    <div class="fw-auth-area">${buildAuthArea(user)}</div>
  </nav>
  <div class="fw-mobile-panel" id="fwMobilePanel">
    ${buildSearch("fw-search fw-mobile-search")}
    <div class="fw-mobile-links">${buildNavLinks(user, "fw-mobile-link")}</div>
  </div>
</header>`;
}

function buildFooter() {
  return `
<footer class="site-footer">
  <p>Copyright &copy; <a href="https://favoriteweb.net/">Favorite Web</a> All Right Reserved</p>
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

function initToolSearch() {
  const inputs = Array.from(document.querySelectorAll(".fw-tool-search-input"));
  if (!inputs.length) return;

  const cards = Array.from(document.querySelectorAll(".service-card"));
  if (!cards.length) {
    inputs.forEach((input) => { input.disabled = true; });
    return;
  }

  const grid = document.querySelector(".services-grid");
  let empty = document.querySelector(".fw-no-tools");
  if (grid && !empty) {
    empty = document.createElement("div");
    empty.className = "fw-no-tools";
    empty.textContent = "No matching tools found.";
    grid.insertAdjacentElement("afterend", empty);
  }

  function applySearch(value) {
    const query = value.trim().toLowerCase();
    let visible = 0;

    cards.forEach((card) => {
      const text = [card.textContent, card.getAttribute("href"), card.dataset.keywords].join(" ").toLowerCase();
      const match = !query || text.includes(query);
      card.classList.toggle("fw-card-hidden", !match);
      if (match) visible += 1;
    });

    if (empty) empty.classList.toggle("show", visible === 0);
    inputs.forEach((input) => {
      if (input.value !== value) input.value = value;
    });
  }

  inputs.forEach((input) => {
    input.addEventListener("input", () => applySearch(input.value));
  });
}

function initNavbarInteractions() {
  const shell = document.querySelector(".fw-nav-shell");
  const toggle = document.querySelector(".fw-menu-toggle");
  const avatar = document.querySelector(".fw-avatar-button");
  const dropdown = document.querySelector(".fw-user-dropdown");

  if (toggle && shell) {
    toggle.addEventListener("click", () => {
      const open = shell.classList.toggle("mobile-open");
      toggle.setAttribute("aria-expanded", String(open));
    });
  }

  if (avatar && dropdown) {
    avatar.addEventListener("click", (event) => {
      event.stopPropagation();
      const open = dropdown.classList.toggle("open");
      avatar.setAttribute("aria-expanded", String(open));
    });
  }

  document.addEventListener("click", (event) => {
    if (dropdown && !event.target.closest(".fw-user-menu")) {
      dropdown.classList.remove("open");
      if (avatar) avatar.setAttribute("aria-expanded", "false");
    }
    if (shell && toggle && !event.target.closest(".fw-nav-shell")) {
      shell.classList.remove("mobile-open");
      toggle.setAttribute("aria-expanded", "false");
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (dropdown) dropdown.classList.remove("open");
    if (avatar) avatar.setAttribute("aria-expanded", "false");
    if (shell) shell.classList.remove("mobile-open");
    if (toggle) toggle.setAttribute("aria-expanded", "false");
  });
}

async function initSharedLayout() {
  let user = { logged_in: false };
  try {
    const res = await fetch("/api/user", { cache: "no-store" });
    if (res.ok) user = await res.json();
  } catch (e) {}

  document.body.insertAdjacentHTML("afterbegin", buildNavbar(user));
  document.body.insertAdjacentHTML("beforeend", buildFooter());

  const existingContent = document.querySelector(".app-shell, .main-content");
  if (!existingContent) {
    const children = Array.from(document.body.children);
    const nav = document.querySelector(".fw-nav-shell");
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
      nav.insertAdjacentElement("afterend", wrapper);
    }
  }

  initNavbarInteractions();
  initToolSearch();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initSharedLayout);
} else {
  initSharedLayout();
}