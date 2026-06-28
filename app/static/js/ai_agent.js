document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("ai-agent-root");
  if (!root) return;

  const cfg = {
    stateUrl: root.dataset.stateUrl,
    activityUrl: root.dataset.activityUrl,
    idleSrc: root.dataset.idleSrc,
    journalingSrc: root.dataset.journalingSrc,
  };

  const AVATAR_SIZE = 144;
  const state = {
    agent_name: "AI助手",
    enabled: true,
    facing: "right",
    position_x: 24,
    position_y: 24,
    daily_rollup_time: "23:59",
    daily_prune_time: "12:00",
  };

  let mode = "idle";
  let idleTimer = 0;
  let saveTimer = 0;
  let saveSeq = 0;
  let lastInteractionReport = 0;

  const shell = document.createElement("div");
  shell.className = "ai-agent-shell is-hidden";

  const reopen = document.createElement("button");
  reopen.className = "ai-agent-reopen is-hidden";
  reopen.type = "button";
  reopen.setAttribute("aria-label", "显示 AI 助手");
  reopen.innerHTML = `<i class="bi bi-stars"></i><span>AI 助手</span>`;

  shell.innerHTML = `
    <button class="ai-agent-avatar" type="button" aria-label="AI Agent">
      <img class="ai-agent-image" alt="" draggable="false">
      <span class="ai-agent-label"></span>
    </button>
    <div class="ai-agent-menu" hidden>
      <div class="ai-agent-menu__title">AI Agent</div>
      <div class="ai-agent-menu__row">
        <label class="form-label ai-agent-menu__mini mb-1" for="ai-agent-name">名字</label>
        <div class="input-group input-group-sm">
          <input id="ai-agent-name" class="form-control" type="text" maxlength="64">
          <button class="btn btn-outline-secondary" type="button" data-agent-action="rename">
            <i class="bi bi-check-lg"></i>
          </button>
        </div>
      </div>
      <div class="ai-agent-menu__row ai-agent-menu__mini text-muted">
        每天 23:59 自动生成当日日志，次日 12:00 自动清理前一天活动数据；周日会基于本周已生成的日志自动生成周记。
      </div>
      <div class="ai-agent-menu__row d-flex flex-wrap gap-2">
        <button class="btn btn-sm btn-outline-secondary" type="button" data-agent-action="face">
          <i class="bi bi-arrow-left-right"></i> 转向
        </button>
        <button class="btn btn-sm btn-outline-danger ms-auto" type="button" data-agent-action="close">
          <i class="bi bi-x-lg"></i> 关闭
        </button>
      </div>
      <div class="ai-agent-menu__row ai-agent-menu__output" data-agent-output hidden></div>
    </div>
  `;

  root.appendChild(shell);
  root.appendChild(reopen);

  const avatar = shell.querySelector(".ai-agent-avatar");
  const image = shell.querySelector(".ai-agent-image");
  const label = shell.querySelector(".ai-agent-label");
  const menu = shell.querySelector(".ai-agent-menu");
  const nameInput = shell.querySelector("#ai-agent-name");
  const output = shell.querySelector("[data-agent-output]");

  function clamp(value, low, high) {
    return Math.min(Math.max(value, low), high);
  }

  function applyState(next) {
    const sanitized = { ...next };
    delete sanitized.scale;
    Object.assign(state, sanitized);

    const x = clamp(Number(state.position_x) || 24, 0, Math.max(0, window.innerWidth - AVATAR_SIZE));
    const y = clamp(Number(state.position_y) || 24, 0, Math.max(0, window.innerHeight - AVATAR_SIZE));

    state.position_x = x;
    state.position_y = y;

    shell.classList.toggle("is-hidden", !state.enabled);
    reopen.classList.toggle("is-hidden", !!state.enabled);
    shell.classList.toggle("is-facing-left", state.facing === "left");
    shell.style.width = `${AVATAR_SIZE}px`;
    shell.style.height = `${AVATAR_SIZE}px`;
    shell.style.left = `${x}px`;
    shell.style.bottom = `${y}px`;
    label.textContent = state.agent_name || "AI助手";
    nameInput.value = state.agent_name || "AI助手";
  }

  async function postJson(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    return data;
  }

  function showOutput(text) {
    output.hidden = false;
    output.textContent = text;
  }

  function saveState(patch) {
    const nextPatch = { ...patch };
    delete nextPatch.scale;
    Object.assign(state, nextPatch);
    applyState(state);
    clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      const seq = ++saveSeq;
      try {
        const data = await postJson(cfg.stateUrl, nextPatch);
        if (seq !== saveSeq) return;
        if (!data.state) return;
        applyState(data.state);
      } catch (err) {
        showOutput(`保存失败：${err.message}`);
      }
    }, 180);
  }

  function setMode(nextMode) {
    mode = nextMode;
    image.src = nextMode === "journaling" ? cfg.journalingSrc : cfg.idleSrc;
    shell.dataset.mode = nextMode;
  }

  function reportActivity(eventType, labelText, metadata) {
    postJson(cfg.activityUrl, {
      event_type: eventType,
      label: labelText,
      metadata: metadata || {},
    }).catch(() => {});
  }

  function bumpJournaling(source) {
    if (!state.enabled || shell.classList.contains("is-hidden")) return;
    setMode("journaling");
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => setMode("idle"), 2200);

    const now = Date.now();
    if (now - lastInteractionReport > 15000) {
      lastInteractionReport = now;
      reportActivity("interaction_active", "用户输入活跃", { source });
    }
  }

  let drag = null;
  avatar.addEventListener("pointerdown", event => {
    if (event.button !== undefined && event.button !== 0) return;
    const rect = shell.getBoundingClientRect();
    drag = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      offsetX: event.clientX - rect.left,
      offsetBottom: rect.bottom - event.clientY,
      width: rect.width,
      height: rect.height,
      moved: false,
    };
    avatar.setPointerCapture(event.pointerId);
    event.preventDefault();
  });

  avatar.addEventListener("pointermove", event => {
    if (!drag || drag.pointerId !== event.pointerId) return;
    const dx = Math.abs(event.clientX - drag.startX);
    const dy = Math.abs(event.clientY - drag.startY);
    if (dx + dy > 4) drag.moved = true;
    if (!drag.moved) return;

    const x = clamp(event.clientX - drag.offsetX, 0, Math.max(0, window.innerWidth - drag.width));
    const y = clamp(window.innerHeight - event.clientY - drag.offsetBottom, 0, Math.max(0, window.innerHeight - drag.height));
    state.position_x = Math.round(x);
    state.position_y = Math.round(y);
    applyState(state);
  });

  avatar.addEventListener("pointerup", event => {
    if (!drag || drag.pointerId !== event.pointerId) return;
    const moved = drag.moved;
    avatar.releasePointerCapture(event.pointerId);
    drag = null;
    if (moved) {
      saveState({ position_x: state.position_x, position_y: state.position_y });
    } else {
      menu.hidden = !menu.hidden;
    }
  });

  shell.addEventListener("click", event => {
    const action = event.target.closest("[data-agent-action]");
    if (!action) return;
    const kind = action.dataset.agentAction;
    if (kind === "rename") {
      saveState({ agent_name: nameInput.value.trim() || "AI助手" });
    } else if (kind === "face") {
      saveState({ facing: state.facing === "left" ? "right" : "left" });
    } else if (kind === "close") {
      menu.hidden = true;
      saveState({ enabled: false });
    }
  });

  document.addEventListener("pointerdown", event => {
    bumpJournaling(event.target.closest("#ai-agent-root") ? "agent" : "mouse");
  }, true);

  document.addEventListener("keydown", () => {
    bumpJournaling("keyboard");
  }, true);

  document.addEventListener("click", event => {
    if (!event.target.closest("#ai-agent-root")) {
      menu.hidden = true;
    }
  });

  reopen.addEventListener("click", () => {
    saveState({ enabled: true });
    menu.hidden = false;
  });

  window.addEventListener("resize", () => {
    applyState(state);
    saveState({ position_x: state.position_x, position_y: state.position_y });
  });

  fetch(cfg.stateUrl)
    .then(response => response.json())
    .then(data => {
      if (data && data.state) {
        applyState(data.state);
        setMode(mode);
        reportActivity("page_view", document.title || location.pathname, {
          path: location.pathname,
          query: location.search,
        });
      }
    })
    .catch(() => {
      shell.classList.add("is-hidden");
    });
});

