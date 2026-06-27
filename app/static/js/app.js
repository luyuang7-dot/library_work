document.addEventListener("DOMContentLoaded", () => {
  setupCsrfProtection();

  setTimeout(() => {
    document.querySelectorAll(".alert.fade.show").forEach((alertEl) => {
      try {
        bootstrap.Alert.getOrCreateInstance(alertEl).close();
      } catch (e) {}
    });
  }, 5000);

  setupThemeToggle();
  setupPageTransitionLoader();
  setupCursorGlow();
});

function setupCsrfProtection() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  const token = meta ? meta.getAttribute("content") : "";
  if (!token) return;

  document.querySelectorAll("form").forEach((form) => {
    const method = (form.getAttribute("method") || "get").toLowerCase();
    if (method !== "post") return;
    if (form.querySelector('input[name="csrf_token"]')) return;

    const input = document.createElement("input");
    input.type = "hidden";
    input.name = "csrf_token";
    input.value = token;
    form.prepend(input);
  });

  const originalFetch = window.fetch.bind(window);
  window.fetch = function(input, init) {
    const requestInit = init ? { ...init } : {};
    const method = resolveFetchMethod(input, requestInit);
    const url = resolveFetchUrl(input);

    if (shouldAttachCsrf(url, method)) {
      const headers = new Headers(
        requestInit.headers ||
        (input instanceof Request ? input.headers : undefined) ||
        {}
      );
      if (!headers.has("X-CSRFToken")) {
        headers.set("X-CSRFToken", token);
      }
      if (!headers.has("X-Requested-With")) {
        headers.set("X-Requested-With", "XMLHttpRequest");
      }
      requestInit.headers = headers;
    }

    return originalFetch(input, requestInit);
  };
}

function resolveFetchMethod(input, init) {
  if (init && init.method) return String(init.method).toUpperCase();
  if (input instanceof Request) return input.method.toUpperCase();
  return "GET";
}

function resolveFetchUrl(input) {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  if (input instanceof Request) return input.url;
  return String(input);
}

function shouldAttachCsrf(url, method) {
  if (["GET", "HEAD", "OPTIONS", "TRACE"].includes(method)) return false;
  try {
    const target = new URL(url, window.location.href);
    return target.origin === window.location.origin;
  } catch (e) {
    return false;
  }
}

function setupThemeToggle() {
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;
  const root = document.documentElement;

  function syncIcons(theme) {
    btn.querySelectorAll("[data-theme-icon]").forEach((icon) => {
      icon.classList.toggle("d-none", icon.dataset.themeIcon !== theme);
    });
  }

  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
    root.setAttribute("data-bs-theme", theme);
    try {
      localStorage.setItem("theme", theme);
    } catch (e) {}
    syncIcons(theme);
  }

  syncIcons(root.getAttribute("data-theme") || "light");

  btn.addEventListener("click", () => {
    const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    applyTheme(next);
  });
}

function setupPageTransitionLoader() {
  const loader = ensurePageLoaderElement();
  const startUrl = new URL(window.location.href);
  let safetyTimer = null;

  function showPageLoader() {
    if (loader.classList.contains("is-visible")) return;
    loader.classList.add("is-visible");
    document.body.classList.add("is-page-transitioning");

    if (safetyTimer) clearTimeout(safetyTimer);
    safetyTimer = setTimeout(() => {
      hidePageLoader();
    }, 1800);
  }

  function hidePageLoader() {
    loader.classList.remove("is-visible");
    document.body.classList.remove("is-page-transitioning");
    if (safetyTimer) {
      clearTimeout(safetyTimer);
      safetyTimer = null;
    }
  }

  function isSamePageHashJump(url) {
    return (
      url.pathname === startUrl.pathname &&
      url.search === startUrl.search &&
      url.hash &&
      url.hash !== startUrl.hash
    );
  }

  function shouldShowForLink(link, event) {
    if (!link || event.defaultPrevented) return false;
    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return false;
    }
    if (link.dataset.noLoader !== undefined) return false;
    if (link.target && link.target !== "_self") return false;
    if (link.hasAttribute("download")) return false;

    const rawHref = (link.getAttribute("href") || "").trim();
    if (!rawHref || rawHref.startsWith("#") || rawHref.startsWith("javascript:")) {
      return false;
    }

    let url;
    try {
      url = new URL(link.href, window.location.href);
    } catch (e) {
      return false;
    }

    if (url.origin !== window.location.origin) return false;
    if (isSamePageHashJump(url)) return false;
    return true;
  }

  function shouldShowForForm(form) {
    if (!form || form.dataset.noLoader !== undefined) return false;
    if (form.target && form.target !== "_self") return false;
    const method = (form.getAttribute("method") || "get").toLowerCase();
    return method !== "dialog";
  }

  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[href]");
    if (!shouldShowForLink(link, event)) return;
    showPageLoader();
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (!shouldShowForForm(form)) return;
    queueMicrotask(() => {
      if (!event.defaultPrevented) showPageLoader();
    });
  });

  window.addEventListener("beforeunload", showPageLoader);
  window.addEventListener("pageshow", hidePageLoader);
  hidePageLoader();
}

function ensurePageLoaderElement() {
  let loader = document.getElementById("page-transition-loader");
  if (loader) return loader;

  loader = document.createElement("div");
  loader.id = "page-transition-loader";
  loader.className = "page-transition-loader";
  loader.setAttribute("aria-hidden", "true");
  loader.innerHTML = `
    <div class="page-transition-loader__panel" role="status" aria-live="polite">
      <span class="spinner-border page-transition-loader__spinner" aria-hidden="true"></span>
      <span class="page-transition-loader__text">Loading page...</span>
    </div>
  `;
  document.body.appendChild(loader);
  return loader;
}

function setupCursorGlow() {
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const supportsFinePointer = window.matchMedia("(pointer: fine)").matches;
  if (prefersReducedMotion || !supportsFinePointer) return;

  const glow = ensureCursorGlowElement();
  const interactiveSelector =
    "a, button, .btn, .nav-link, .list-group-item-action, input, select, textarea, [role='button']";

  let targetX = window.innerWidth / 2;
  let targetY = window.innerHeight / 2;
  let currentX = targetX;
  let currentY = targetY;
  let rafId = 0;
  const ease = 0.2;

  function updateFrame() {
    currentX += (targetX - currentX) * ease;
    currentY += (targetY - currentY) * ease;
    glow.style.transform =
      `translate3d(${currentX}px, ${currentY}px, 0) translate(-50%, -50%)`;

    if (Math.abs(targetX - currentX) > 0.08 || Math.abs(targetY - currentY) > 0.08) {
      rafId = window.requestAnimationFrame(updateFrame);
    } else {
      rafId = 0;
    }
  }

  function queueFrame() {
    if (!rafId) rafId = window.requestAnimationFrame(updateFrame);
  }

  document.addEventListener("mousemove", (event) => {
    targetX = event.clientX;
    targetY = event.clientY;
    if (!glow.classList.contains("is-visible")) {
      glow.classList.add("is-visible");
    }
    queueFrame();
  });

  document.addEventListener("mouseleave", () => {
    glow.classList.remove("is-visible", "is-hovering", "is-pressed");
  });

  document.addEventListener("mousedown", () => {
    glow.classList.add("is-pressed");
  });

  document.addEventListener("mouseup", () => {
    glow.classList.remove("is-pressed");
  });

  document.addEventListener("mouseover", (event) => {
    if (event.target.closest(interactiveSelector)) {
      glow.classList.add("is-hovering");
    }
  });

  document.addEventListener("mouseout", (event) => {
    const next = event.relatedTarget;
    if (next && next.closest && next.closest(interactiveSelector)) return;
    glow.classList.remove("is-hovering");
  });

  window.addEventListener("blur", () => {
    glow.classList.remove("is-visible", "is-hovering", "is-pressed");
  });
}

function ensureCursorGlowElement() {
  let glow = document.getElementById("cursor-glow");
  if (glow) return glow;

  glow = document.createElement("div");
  glow.id = "cursor-glow";
  glow.className = "cursor-glow";
  glow.setAttribute("aria-hidden", "true");
  document.body.appendChild(glow);
  return glow;
}
