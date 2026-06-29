document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("ai-assistant-root");
  if (!root) return;

  const cfg = {
    stateUrl: root.dataset.stateUrl,
    activityUrl: root.dataset.activityUrl,
    rollupUrl: root.dataset.rollupUrl,
    journalsUrl: root.dataset.journalsUrl,
    libraryUrl: root.dataset.libraryUrl,
    searchUrl: root.dataset.searchUrl,
    avatarSrc: root.dataset.avatarSrc,
  };

  const defaults = {
    agent_name: "Eyjafjalla",
    enabled: true,
    user_preference: "",
    daily_rollup_time: "23:59",
    daily_prune_time: "12:00",
  };

  const moodCopy = {
    sleepy: {
      badge: "Sleepy",
      bubble: "I will stay quietly in the corner. Click me and a small control window will open beside me.",
      note: "Low-profile standby mode for quiet cataloging and cleanup.",
    },
    active: {
      badge: "Active",
      bubble: "I am watching your page activity and can quickly jump to your library, search, or journals.",
      note: "More proactive nudges while you browse and switch pages.",
    },
    focus: {
      badge: "Focus",
      bubble: "I will reduce interruptions and keep only the most useful reminders nearby.",
      note: "Calmer pacing for sustained entry, editing, and review work.",
    },
  };

  const state = {
    ...defaults,
    mode: "sleepy",
    panelOpen: false,
    bubbleVisible: false,
    posX: null,
    posY: null,
  };

  const quickActions = [
    {
      label: "文献库",
      icon: "bi-journal-text",
      eventType: "assistant_shortcut",
      bubble: "带你回到文献库主页。",
      onClick() {
        location.href = cfg.libraryUrl;
      },
    },
    {
      label: "搜索",
      icon: "bi-search",
      eventType: "assistant_shortcut",
      bubble: "打开搜索页，继续找资料。",
      onClick() {
        location.href = cfg.searchUrl;
      },
    },
    {
      label: "日志看板",
      icon: "bi-journal-medical",
      eventType: "assistant_shortcut",
      bubble: "带你去看今天和本周的 AI 日志。",
      onClick() {
        location.href = cfg.journalsUrl;
      },
    },
    {
      label: "生成日志",
      icon: "bi-stars",
      eventType: "assistant_rollup",
      async onClick() {
        if (!state.enabled) {
          showBubble("AI 日志功能当前已暂停，但悬浮助手仍然可用。", "sleepy");
          return;
        }

        showBubble("我正在尝试为你生成当前可用的日志摘要。", "active");
        try {
          const result = await postJson(cfg.rollupUrl, {});
          const daily = Array.isArray(result) ? result[0] : result;
          if (daily && daily.ok && !daily.skipped) {
            showBubble("日志已经生成好了，可以去日志看板查看。", "active");
          } else if (daily && daily.reason === "not_due") {
            showBubble("还没到自动汇总时间，我先帮你记住当前节奏。", "focus");
          } else {
            showBubble("这次没有新的日志内容需要生成。", "sleepy");
          }
        } catch (error) {
          showBubble(`生成日志失败：${error.message}`, "focus");
        }
      },
    },
  ];

  const feedItems = [
    {
      tag: "联动",
      text: "我会记录关键页面动作，帮助后续生成当天和本周的活动日志。",
    },
    {
      tag: "交互",
      text: "头像可以拖动定位，控制窗会始终贴着头像一起移动。",
    },
    {
      tag: "节奏",
      text: "默认每天 23:59 汇总日志，次日 12:00 清理上一日活动记录。",
    },
  ];

  const assistant = document.createElement("section");
  assistant.className = "ai-assistant";
  assistant.dataset.state = state.mode;
  assistant.innerHTML = `
    <div class="ai-assistant__bubble" hidden>
      <div class="ai-assistant__bubble-title">
        <span>Eyjafjalla</span>
        <span data-assistant-bubble-state>Sleepy</span>
      </div>
      <div class="ai-assistant__bubble-body" data-assistant-bubble-body></div>
    </div>
    <div class="ai-assistant__shell">
      <div class="ai-assistant__spot"></div>
      <button class="ai-assistant__avatar" type="button" aria-label="打开悬浮助手">
        <img alt="悬浮助手" draggable="false">
        <span class="ai-assistant__badge">
          <span class="ai-assistant__badge-dot"></span>
          <span data-assistant-badge>Sleepy</span>
        </span>
      </button>
      <div class="ai-assistant__status" data-assistant-status>
        <i class="bi bi-moon-stars"></i>
        <span></span>
      </div>
    </div>
  `;

  const panel = document.createElement("section");
  panel.className = "ai-assistant__panel ai-assistant__panel--floating";
  panel.hidden = true;
  panel.innerHTML = `
    <div class="ai-assistant__panel-head">
      <div>
        <h3 class="ai-assistant__panel-title">悬浮助手控制窗</h3>
        <p class="ai-assistant__panel-subtitle" data-assistant-panel-note></p>
      </div>
      <button class="ai-assistant__close" type="button" aria-label="关闭助手面板">
        <i class="bi bi-x-lg"></i>
      </button>
    </div>
    <div class="ai-assistant__chips" data-assistant-modes></div>
    <div class="ai-assistant__name">
      <label for="ai-assistant-name">称呼</label>
      <div class="input-group input-group-sm">
        <input id="ai-assistant-name" class="form-control" type="text" maxlength="64">
        <button class="btn btn-outline-secondary" type="button" data-assistant-action="save-name">
          <i class="bi bi-check-lg"></i>
        </button>
      </div>
    </div>
    <div class="ai-assistant__feed" data-assistant-feed></div>
    <div class="ai-assistant__actions" data-assistant-actions></div>
    <div class="ai-assistant__footer">
      我会把你的关键点击与页面节奏联动到活动日志里，但不会替你修改文献内容。
    </div>
  `;

  root.appendChild(assistant);
  document.body.appendChild(panel);

  const bubble = assistant.querySelector(".ai-assistant__bubble");
  const bubbleBody = assistant.querySelector("[data-assistant-bubble-body]");
  const bubbleState = assistant.querySelector("[data-assistant-bubble-state]");
  const avatar = assistant.querySelector(".ai-assistant__avatar");
  const avatarImg = assistant.querySelector("img");
  const badge = assistant.querySelector("[data-assistant-badge]");
  const statusText = assistant.querySelector("[data-assistant-status] span");
  const panelNote = panel.querySelector("[data-assistant-panel-note]");
  const nameInput = panel.querySelector("#ai-assistant-name");
  const modesRoot = panel.querySelector("[data-assistant-modes]");
  const feedRoot = panel.querySelector("[data-assistant-feed]");
  const actionsRoot = panel.querySelector("[data-assistant-actions]");
  const closeBtn = panel.querySelector(".ai-assistant__close");

  avatarImg.src = cfg.avatarSrc;

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function currentModeMeta(mode = state.mode) {
    return moodCopy[mode] || moodCopy.sleepy;
  }

  function buildStatusText(mode = state.mode) {
    if (!state.enabled) {
      return "AI 日志已暂停，悬浮助手仍然可用";
    }
    if (mode === "sleepy") return `今天 ${state.daily_rollup_time} 自动汇总`;
    if (mode === "active") return "我会更积极地提醒最近活动";
    return "我会减少打扰，只保留关键提示";
  }

  function readAssistantRect() {
    return assistant.getBoundingClientRect();
  }

  function positionPanel() {
    if (panel.hidden) return;

    const assistantRect = readAssistantRect();
    const panelRect = panel.getBoundingClientRect();
    const gap = 14;
    const margin = 12;

    let left = assistantRect.right + gap;
    let top = assistantRect.top;

    if (left + panelRect.width > window.innerWidth - margin) {
      left = assistantRect.left - panelRect.width - gap;
    }
    if (left < margin) {
      left = clamp(window.innerWidth - panelRect.width - margin, margin, window.innerWidth - margin);
    }

    if (top + panelRect.height > window.innerHeight - margin) {
      top = window.innerHeight - panelRect.height - margin;
    }
    top = Math.max(margin, top);

    panel.style.left = `${left}px`;
    panel.style.top = `${top}px`;
    panel.style.right = "auto";
  }

  function setFloatingPosition(x, y) {
    if (x == null || y == null) {
      assistant.style.removeProperty("left");
      assistant.style.removeProperty("top");
      assistant.style.removeProperty("right");
      assistant.style.removeProperty("bottom");
      positionPanel();
      return;
    }

    const rect = readAssistantRect();
    const nextX = clamp(x, 8, window.innerWidth - rect.width - 8);
    const nextY = clamp(y, 8, window.innerHeight - rect.height - 8);
    assistant.style.left = `${nextX}px`;
    assistant.style.top = `${nextY}px`;
    assistant.style.right = "auto";
    assistant.style.bottom = "auto";
    state.posX = nextX;
    state.posY = nextY;
    persistLocalState();
    positionPanel();
  }

  function persistLocalState() {
    try {
      localStorage.setItem(
        "ai-assistant-ui-state",
        JSON.stringify({
          mode: state.mode,
          posX: state.posX,
          posY: state.posY,
        }),
      );
    } catch (error) {}
  }

  function loadLocalState() {
    try {
      const raw = localStorage.getItem("ai-assistant-ui-state");
      if (!raw) return;
      const saved = JSON.parse(raw);
      if (saved && typeof saved === "object") {
        if (saved.mode && moodCopy[saved.mode]) state.mode = saved.mode;
        if (Number.isFinite(saved.posX)) state.posX = saved.posX;
        if (Number.isFinite(saved.posY)) state.posY = saved.posY;
      }
    } catch (error) {}
  }

  function showBubble(text, mode = state.mode) {
    const meta = currentModeMeta(mode);
    assistant.dataset.state = mode;
    bubble.hidden = false;
    bubble.classList.add("is-visible");
    state.bubbleVisible = true;
    bubbleBody.textContent = text;
    bubbleState.textContent = meta.badge;
    badge.textContent = meta.badge;
  }

  function hideBubble() {
    state.bubbleVisible = false;
    bubble.classList.remove("is-visible");
    setTimeout(() => {
      if (!state.bubbleVisible) {
        bubble.hidden = true;
      }
    }, 180);
  }

  function renderModes() {
    modesRoot.innerHTML = "";
    Object.entries(moodCopy).forEach(([key, meta]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `ai-assistant__chip${state.mode === key ? " is-active" : ""}`;
      button.textContent = meta.badge;
      button.addEventListener("click", () => {
        state.mode = key;
        panelNote.textContent = meta.note;
        statusText.textContent = buildStatusText(key);
        renderModes();
        showBubble(meta.bubble, key);
        reportActivity("assistant_mode_change", `切换助手状态：${meta.badge}`, { mode: key });
        persistLocalState();
      });
      modesRoot.appendChild(button);
    });
  }

  function renderFeed() {
    feedRoot.innerHTML = "";
    feedItems.forEach((item, index) => {
      const row = document.createElement("article");
      row.className = "ai-assistant__feed-item";

      const meta = document.createElement("div");
      meta.className = "ai-assistant__feed-meta";
      const tag = document.createElement("span");
      tag.textContent = item.tag;
      const indexText = document.createElement("span");
      indexText.textContent = `#${index + 1}`;
      meta.append(tag, indexText);

      const text = document.createElement("div");
      text.className = "ai-assistant__feed-text";
      text.textContent = item.text;

      row.append(meta, text);
      feedRoot.appendChild(row);
    });
  }

  function renderActions() {
    actionsRoot.innerHTML = "";
    quickActions.forEach(action => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-outline-secondary btn-sm";
      button.innerHTML = `<i class="bi ${action.icon}"></i> ${action.label}`;
      button.addEventListener("click", async () => {
        reportActivity(action.eventType, `点击快捷操作：${action.label}`, { label: action.label });
        if (action.bubble) {
          showBubble(action.bubble, "active");
        }
        await action.onClick();
      });
      actionsRoot.appendChild(button);
    });
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

  async function reportActivity(eventType, label, metadata) {
    try {
      await postJson(cfg.activityUrl, {
        event_type: eventType,
        label,
        metadata: metadata || {},
      });
    } catch (error) {}
  }

  function openPanel() {
    panel.hidden = false;
    state.panelOpen = true;
    panelNote.textContent = currentModeMeta().note;
    positionPanel();
    showBubble(currentModeMeta().bubble, state.mode);
  }

  function closePanel() {
    panel.hidden = true;
    state.panelOpen = false;
    hideBubble();
  }

  function togglePanel() {
    if (state.panelOpen) {
      closePanel();
    } else {
      openPanel();
    }
  }

  function syncServerState(next) {
    Object.assign(state, next || {});
    nameInput.value = state.agent_name || defaults.agent_name;
    statusText.textContent = buildStatusText();
    assistant.dataset.state = state.mode;
    panelNote.textContent = currentModeMeta().note;
    badge.textContent = currentModeMeta().badge;
  }

  loadLocalState();
  renderModes();
  renderFeed();
  renderActions();
  syncServerState(state);
  showBubble(currentModeMeta().bubble, state.mode);

  fetch(cfg.stateUrl)
    .then(response => response.json())
    .then(data => {
      if (data && data.state) {
        syncServerState({ ...data.state, mode: state.mode });
      }
    })
    .catch(() => {});

  if (state.posX != null && state.posY != null) {
    requestAnimationFrame(() => setFloatingPosition(state.posX, state.posY));
  } else {
    requestAnimationFrame(positionPanel);
  }

  let drag = null;
  avatar.addEventListener("pointerdown", event => {
    if (event.button !== undefined && event.button !== 0) return;
    const rect = readAssistantRect();
    drag = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
      moved: false,
    };
    avatar.setPointerCapture(event.pointerId);
  });

  avatar.addEventListener("pointermove", event => {
    if (!drag || drag.pointerId !== event.pointerId) return;
    const dx = Math.abs(event.clientX - drag.startX);
    const dy = Math.abs(event.clientY - drag.startY);
    if (dx + dy > 6) {
      drag.moved = true;
    }
    if (!drag.moved) return;
    setFloatingPosition(event.clientX - drag.offsetX, event.clientY - drag.offsetY);
  });

  avatar.addEventListener("pointerup", event => {
    if (!drag || drag.pointerId !== event.pointerId) return;
    avatar.releasePointerCapture(event.pointerId);
    const moved = drag.moved;
    drag = null;

    if (moved) {
      reportActivity("assistant_drag", "拖动悬浮助手", {
        x: state.posX,
        y: state.posY,
      });
      showBubble("我已经挪到新的位置啦，控制窗会继续跟着我。", "focus");
      return;
    }

    togglePanel();
    reportActivity(
      "assistant_panel_toggle",
      state.panelOpen ? "展开跟随助手窗" : "收起跟随助手窗",
      { open: state.panelOpen },
    );
  });

  closeBtn.addEventListener("click", () => {
    closePanel();
    reportActivity("assistant_panel_toggle", "收起跟随助手窗", { open: false });
  });

  panel.addEventListener("click", event => {
    const action = event.target.closest("[data-assistant-action]");
    if (!action) return;

    if (action.dataset.assistantAction === "save-name") {
      const nextName = nameInput.value.trim() || defaults.agent_name;
      postJson(cfg.stateUrl, { agent_name: nextName })
        .then(data => {
          if (data && data.state) {
            syncServerState({ ...data.state, mode: state.mode });
            showBubble(`好的，以后我就叫“${nextName}”。`, "active");
            reportActivity("assistant_rename", "修改助手称呼", { agent_name: nextName });
          }
        })
        .catch(error => {
          showBubble(`名称保存失败：${error.message}`, "focus");
        });
    }
  });

  const bubbleSchedule = [
    "我会把你的关键动作轻轻记下来，等到晚上再整理成日志。",
    "如果你只想安静录入文献，我会尽量少说话。",
    "拖动角色以后，控制窗会始终贴着角色一起移动。",
  ];

  let bubbleIndex = 0;
  setInterval(() => {
    if (state.panelOpen) return;
    bubbleIndex = (bubbleIndex + 1) % bubbleSchedule.length;
    showBubble(bubbleSchedule[bubbleIndex], state.mode);
    setTimeout(() => {
      if (!state.panelOpen) {
        hideBubble();
      }
    }, 4200);
  }, 14000);

  document.addEventListener("pointerdown", event => {
    if (!event.target.closest(".ai-assistant") && !event.target.closest(".ai-assistant__panel")) {
      closePanel();
    }
  });

  document.addEventListener(
    "keydown",
    event => {
      if (event.key === "Escape") {
        closePanel();
      } else if (state.mode === "sleepy") {
        state.mode = "focus";
        renderModes();
        syncServerState(state);
      }
    },
    true,
  );

  let lastActivityReport = 0;
  function handleObservedActivity(kind) {
    const now = Date.now();
    if (now - lastActivityReport < 12000) return;
    lastActivityReport = now;
    reportActivity("assistant_observe", `检测到页面活跃：${kind}`, { source: kind });
    if (kind === "click" || kind === "keyboard") {
      state.mode = "active";
      renderModes();
      syncServerState(state);
    }
  }

  document.addEventListener(
    "click",
    event => {
      if (!event.target.closest(".ai-assistant") && !event.target.closest(".ai-assistant__panel")) {
        handleObservedActivity("click");
      }
    },
    true,
  );

  document.addEventListener(
    "keydown",
    () => {
      handleObservedActivity("keyboard");
    },
    true,
  );

  window.addEventListener("resize", () => {
    if (state.posX != null && state.posY != null) {
      setFloatingPosition(state.posX, state.posY);
    } else {
      positionPanel();
    }
  });

  window.addEventListener("scroll", positionPanel, true);
});
