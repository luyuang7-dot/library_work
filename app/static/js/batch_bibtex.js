/* 批量 PDF 识别与表单导入。 */
(function () {
  "use strict";

  const MAX_FILES = 20;
  const LS_PREFIX = "batchform:v1:";
  const LS_TTL_MS = 7 * 24 * 60 * 60 * 1000;
  const DRAFT_DEBOUNCE_MS = 500;

  const root = document.getElementById("batch-app");
  if (!root) return;

  const recognizeUrl = root.dataset.recognizeUrl;
  const importUrl = root.dataset.importUrl;
  const healthUrl = root.dataset.healthUrl;

  const els = {
    empty: document.getElementById("state-empty"),
    working: document.getElementById("state-working"),
    input: document.getElementById("pdf-input"),
    pickBtn: document.getElementById("pick-files-btn"),
    list: document.getElementById("file-list"),
    count: document.getElementById("file-count"),
    retryBtn: document.getElementById("retry-failed-btn"),
    submitBtn: document.getElementById("submit-all-btn"),
    emptyPane: document.getElementById("empty-pane"),
    splitPane: document.getElementById("split-pane"),
    mdFilename: document.getElementById("md-filename"),
    mdStatus: document.getElementById("md-status"),
    mdRender: document.getElementById("md-render"),
    summary: document.getElementById("result-summary"),
    defaultCategory: document.getElementById("default-category"),
    form: document.getElementById("batch-form"),
    formFeedback: document.getElementById("form-feedback"),
  };

  const formFields = {
    title: document.getElementById("form-title"),
    document_type: document.getElementById("form-document-type"),
    source_type: document.getElementById("form-source-type"),
    publication_year: document.getElementById("form-publication-year"),
    source_name: document.getElementById("form-source-name"),
    publisher_name: document.getElementById("form-publisher-name"),
    volume: document.getElementById("form-volume"),
    issue: document.getElementById("form-issue"),
    pages: document.getElementById("form-pages"),
    authors_raw: document.getElementById("form-authors-raw"),
    keywords_raw: document.getElementById("form-keywords-raw"),
    tags_raw: document.getElementById("form-tags-raw"),
    doi: document.getElementById("form-doi"),
    abstract: document.getElementById("form-abstract"),
    notes: document.getElementById("form-notes"),
    reading_status: document.getElementById("form-reading-status"),
    category_id: document.getElementById("form-category-id"),
  };

  const statusLabel = {
    queued: { icon: "•", text: "排队中", badge: "secondary", textClass: "text-muted" },
    recognizing: { icon: "…", text: "识别中", badge: "primary", textClass: "text-primary" },
    recognized: { icon: "✓", text: "待检查", badge: "success", textClass: "text-success" },
    rec_failed: { icon: "!", text: "识别失败", badge: "danger", textClass: "text-danger" },
    submitting: { icon: "…", text: "入库中", badge: "primary", textClass: "text-primary" },
    imported: { icon: "✓", text: "已入库", badge: "success", textClass: "text-success" },
    import_failed: { icon: "!", text: "入库失败", badge: "danger", textClass: "text-danger" },
    skipped: { icon: "-", text: "已跳过", badge: "warning", textClass: "text-warning" },
  };

  const items = [];
  let activeIndex = null;
  let recognizeBusy = false;
  let submitBusy = false;
  let draftTimer = null;

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[char]);
  }

  function blankFormData() {
    return {
      title: "",
      document_type: "journal_article",
      source_type: "journal",
      publication_year: "",
      source_name: "",
      publisher_name: "",
      volume: "",
      issue: "",
      pages: "",
      authors_raw: "",
      keywords_raw: "",
      tags_raw: "",
      doi: "",
      abstract: "",
      notes: "",
      reading_status: "unread",
      category_id: "",
    };
  }

  function normalizeFormData(raw) {
    return Object.assign(blankFormData(), raw || {});
  }

  function buildAuthorsRaw(authors) {
    if (!Array.isArray(authors)) return "";
    return authors.map((author) => String(author || "").trim()).filter(Boolean).join("\n");
  }

  function buildKeywordsRaw(keywords) {
    if (!Array.isArray(keywords)) return "";
    return keywords.map((keyword) => String(keyword || "").trim()).filter(Boolean).join(", ");
  }

  function draftKey(id) {
    return `${LS_PREFIX}${id}`;
  }

  function loadDraft(id) {
    try {
      const raw = localStorage.getItem(draftKey(id));
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (Date.now() - parsed.ts > LS_TTL_MS) {
        localStorage.removeItem(draftKey(id));
        return null;
      }
      return normalizeFormData(parsed.form);
    } catch (error) {
      return null;
    }
  }

  function saveDraft(id, form) {
    try {
      localStorage.setItem(draftKey(id), JSON.stringify({ ts: Date.now(), form }));
    } catch (error) {
      console.warn("draft save failed", error);
    }
  }

  function clearDraft(id) {
    try {
      localStorage.removeItem(draftKey(id));
    } catch (error) {
      // ignore
    }
  }

  function purgeOldDrafts() {
    try {
      for (let index = localStorage.length - 1; index >= 0; index -= 1) {
        const key = localStorage.key(index);
        if (!key || !key.startsWith(LS_PREFIX)) continue;
        try {
          const parsed = JSON.parse(localStorage.getItem(key));
          if (!parsed || Date.now() - parsed.ts > LS_TTL_MS) {
            localStorage.removeItem(key);
          }
        } catch (error) {
          localStorage.removeItem(key);
        }
      }
    } catch (error) {
      // ignore
    }
  }

  function fileId(file) {
    return `${file.name}|${file.size}|${file.lastModified}`;
  }

  function getFormState() {
    const result = {};
    Object.keys(formFields).forEach((key) => {
      result[key] = formFields[key].value;
    });
    return normalizeFormData(result);
  }

  function applyFormState(formData) {
    const normalized = normalizeFormData(formData);
    Object.keys(formFields).forEach((key) => {
      formFields[key].value = normalized[key];
    });
  }

  function hasMeaningfulFormData(item) {
    return Boolean((item.formData.title || "").trim());
  }

  function inferSourceType(sourceName) {
    const value = String(sourceName || "").toLowerCase();
    if (!value) return "journal";
    if (
      value.includes("conference") ||
      value.includes("proceedings") ||
      value.includes("symposium") ||
      value.includes("workshop")
    ) {
      return "conference";
    }
    return "journal";
  }

  function inferDocumentType(sourceType) {
    return sourceType === "conference" ? "conference_paper" : "journal_article";
  }

  function applySuggestedFields(item, suggestedFields) {
    const base = item.formData || blankFormData();
    const sourceName = suggestedFields.source || base.source_name || "";
    const sourceType = inferSourceType(sourceName);

    item.formData = normalizeFormData({
      ...base,
      title: suggestedFields.title || base.title,
      publication_year: suggestedFields.year ? String(suggestedFields.year) : base.publication_year,
      source_name: sourceName || base.source_name,
      source_type: base.source_type || sourceType,
      document_type: base.document_type || inferDocumentType(sourceType),
      authors_raw: buildAuthorsRaw(suggestedFields.authors) || base.authors_raw,
      keywords_raw: buildKeywordsRaw(suggestedFields.keywords) || base.keywords_raw,
      doi: suggestedFields.doi || base.doi,
      abstract: suggestedFields.abstract || base.abstract,
    });
  }

  function renderMarkdown(markdown) {
    if (!markdown) {
      els.mdRender.innerHTML = '<div class="text-muted">暂无 Markdown 内容。</div>';
      return;
    }
    if (markdown.length > 200 * 1024) {
      els.mdRender.innerHTML = `<div class="alert alert-warning">内容较长，仅显示前 50KB。</div><pre style="white-space: pre-wrap;">${escapeHtml(markdown.slice(0, 50 * 1024))}</pre>`;
      return;
    }
    try {
      els.mdRender.innerHTML = window.marked.parse(markdown);
    } catch (error) {
      els.mdRender.innerHTML = `<pre style="white-space: pre-wrap;">${escapeHtml(markdown)}</pre>`;
    }
  }

  function renderFormFeedback(item) {
    const notes = [];
    if (!(item.formData.title || "").trim()) notes.push("建议先补全标题");
    if (!(item.formData.authors_raw || "").trim()) notes.push("作者尚未填写");
    if (!(item.formData.abstract || "").trim()) notes.push("摘要尚未填写");
    if (item.status === "import_failed" && item.errorMsg) notes.push(`上次入库失败：${item.errorMsg}`);

    if (notes.length === 0) {
      els.formFeedback.textContent = "信息已较完整，可以直接批量提交。";
      els.formFeedback.className = "small text-success mt-3";
      return;
    }

    els.formFeedback.textContent = notes.join("；");
    els.formFeedback.className = "small text-muted mt-3";
  }

  function renderList() {
    els.count.textContent = String(items.length);
    els.list.innerHTML = "";
    items.forEach((item, index) => {
      const status = statusLabel[item.status] || statusLabel.queued;
      const li = document.createElement("li");
      li.className = "list-group-item list-group-item-action d-flex justify-content-between align-items-center";
      if (index === activeIndex) li.classList.add("active");
      li.innerHTML = `
        <span class="text-truncate" style="max-width: 70%;" title="${escapeHtml(item.filename)}">${escapeHtml(item.filename)}</span>
        <span class="${status.textClass}" title="${escapeHtml(item.errorMsg || status.text)}">${status.icon} ${status.text}</span>
      `;
      li.addEventListener("click", () => selectItem(index));
      els.list.appendChild(li);
    });
    refreshButtons();
  }

  function refreshButtons() {
    const busy = recognizeBusy || submitBusy;
    els.retryBtn.disabled = busy || !items.some((item) => item.status === "rec_failed");
    els.submitBtn.disabled = busy || !items.some((item) => {
      return (item.status === "recognized" || item.status === "import_failed") && hasMeaningfulFormData(item);
    });
  }

  function selectItem(index) {
    activeIndex = index;
    const item = items[index];
    if (!item) return;

    renderList();
    els.emptyPane.classList.add("d-none");
    els.splitPane.classList.remove("d-none");
    els.mdFilename.textContent = item.filename;

    const status = statusLabel[item.status] || statusLabel.queued;
    els.mdStatus.textContent = `${status.icon} ${status.text}`;
    els.mdStatus.className = `badge bg-${status.badge}`;

    if (item.status === "rec_failed") {
      els.mdRender.innerHTML = `<div class="alert alert-danger">${escapeHtml(item.errorMsg || "识别失败")}</div>`;
    } else if (item.status === "queued" || item.status === "recognizing" || item.status === "submitting") {
      els.mdRender.innerHTML = '<div class="text-muted">处理中，请稍候。</div>';
    } else {
      renderMarkdown(item.markdown || "");
    }

    applyFormState(item.formData);
    renderFormFeedback(item);
  }

  async function recognizeOne(item) {
    const formData = new FormData();
    formData.append("pdf", item.file, item.filename);

    const response = await fetch(recognizeUrl, { method: "POST", body: formData });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    item.markdown = payload.markdown || "";
    item.errorMsg = null;
    applySuggestedFields(item, payload.suggested_fields || {});
  }

  async function pumpRecognizeQueue() {
    if (recognizeBusy) return;
    const nextItem = items.find((item) => item.status === "queued");
    if (!nextItem) {
      renderList();
      return;
    }

    recognizeBusy = true;
    nextItem.status = "recognizing";
    renderList();

    try {
      await recognizeOne(nextItem);
      nextItem.status = "recognized";
    } catch (error) {
      nextItem.status = "rec_failed";
      nextItem.errorMsg = String(error);
    } finally {
      recognizeBusy = false;
      renderList();
      if (activeIndex !== null && items[activeIndex] === nextItem) {
        selectItem(activeIndex);
      }
      pumpRecognizeQueue();
    }
  }

  function onFilesPicked(fileList) {
    const files = Array.from(fileList).filter((file) => file.name.toLowerCase().endsWith(".pdf"));
    if (!files.length) {
      alert("请选择 PDF 文件。");
      return;
    }
    if (files.length > MAX_FILES) {
      alert(`单次最多 ${MAX_FILES} 篇，本次选择了 ${files.length} 篇。`);
      return;
    }

    purgeOldDrafts();
    files.forEach((file) => {
      const id = fileId(file);
      if (items.some((item) => item.id === id)) return;
      items.push({
        id,
        file,
        filename: file.name,
        status: "queued",
        markdown: "",
        formData: loadDraft(id) || blankFormData(),
        errorMsg: null,
        documentId: null,
      });
    });

    els.empty.classList.add("d-none");
    els.working.classList.remove("d-none");
    renderList();
    if (activeIndex === null && items.length) {
      selectItem(0);
    }
    pumpRecognizeQueue();
  }

  async function runSubmitQueue() {
    submitBusy = true;
    refreshButtons();

    const defaultCategoryId = els.defaultCategory.value || "";
    let success = 0;
    let skipped = 0;
    let failed = 0;
    const failures = [];

    for (const item of items) {
      if (item.status === "imported") continue;
      if (item.status === "rec_failed") {
        item.status = "skipped";
        item.errorMsg = "识别未成功";
        skipped += 1;
        renderList();
        continue;
      }
      if (item.status !== "recognized" && item.status !== "import_failed") continue;
      if (!hasMeaningfulFormData(item)) {
        item.status = "skipped";
        item.errorMsg = "标题不能为空";
        skipped += 1;
        renderList();
        continue;
      }

      item.status = "submitting";
      item.errorMsg = null;
      renderList();
      if (activeIndex !== null && items[activeIndex] === item) {
        selectItem(activeIndex);
      }

      try {
        const formData = new FormData();
        formData.append("pdf", item.file, item.filename);
        Object.entries(item.formData).forEach(([key, value]) => {
          if (value !== null && value !== undefined) {
            formData.append(key, value);
          }
        });
        if (defaultCategoryId) {
          formData.append("default_category_id", defaultCategoryId);
        }

        const response = await fetch(importUrl, { method: "POST", body: formData });
        const payload = await response.json();
        if (response.ok && payload.ok) {
          item.status = "imported";
          item.documentId = payload.document_id;
          clearDraft(item.id);
          success += 1;
        } else if (
          response.ok &&
          payload.ok === false &&
          (payload.reason === "duplicate" || payload.reason === "missing_title")
        ) {
          item.status = "skipped";
          item.errorMsg = payload.error_detail || payload.reason;
          skipped += 1;
        } else {
          item.status = "import_failed";
          item.errorMsg = payload.error_detail || payload.error || payload.reason || `HTTP ${response.status}`;
          failed += 1;
          failures.push({ filename: item.filename, reason: item.errorMsg });
        }
      } catch (error) {
        item.status = "import_failed";
        item.errorMsg = String(error);
        failed += 1;
        failures.push({ filename: item.filename, reason: item.errorMsg });
      }

      renderList();
      if (activeIndex !== null && items[activeIndex] === item) {
        selectItem(activeIndex);
      }
    }

    submitBusy = false;
    renderList();
    showSummary(success, skipped, failed, failures);
  }

  function showSummary(success, skipped, failed, failures) {
    let html = `批量提交完成：<strong class="text-success">${success} 成功</strong> · <strong class="text-warning">${skipped} 跳过</strong> · <strong class="text-danger">${failed} 失败</strong>`;
    if (success > 0) {
      html += ' · <a href="/documents">查看文献库</a>';
    }
    if (failures.length > 0) {
      html += '<ul class="mt-2 mb-0">';
      failures.forEach((failure) => {
        html += `<li><code>${escapeHtml(failure.filename)}</code>：${escapeHtml(failure.reason)}</li>`;
      });
      html += "</ul>";
    }
    els.summary.innerHTML = html;
    els.summary.className = failed > 0 ? "alert alert-warning mt-3" : "alert alert-success mt-3";
    els.summary.classList.remove("d-none");
  }

  els.pickBtn.addEventListener("click", () => els.input.click());
  els.input.addEventListener("change", (event) => onFilesPicked(event.target.files));

  els.retryBtn.addEventListener("click", () => {
    items.forEach((item) => {
      if (item.status === "rec_failed") {
        item.status = "queued";
        item.errorMsg = null;
      }
    });
    renderList();
    pumpRecognizeQueue();
  });

  els.submitBtn.addEventListener("click", runSubmitQueue);

  els.form.addEventListener("input", () => {
    if (activeIndex === null) return;
    const item = items[activeIndex];
    item.formData = getFormState();
    renderFormFeedback(item);
    clearTimeout(draftTimer);
    draftTimer = setTimeout(() => saveDraft(item.id, item.formData), DRAFT_DEBOUNCE_MS);
    refreshButtons();
  });

  window.addEventListener("beforeunload", (event) => {
    const dirty = items.some((item) => {
      return (item.status === "recognized" || item.status === "rec_failed" || item.status === "import_failed") && hasMeaningfulFormData(item);
    });
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = "当前还有未提交的批量入库草稿，确认离开吗？";
    return event.returnValue;
  });

  purgeOldDrafts();

  (async function checkHealth() {
    try {
      const response = await fetch(healthUrl);
      const payload = await response.json();
      if (payload.ok) return;
      const banner = document.getElementById("mineru-banner");
      const message = document.getElementById("mineru-banner-msg");
      if (banner && message) {
        message.textContent = `MinerU 当前不可用：${payload.error}（${payload.url}）`;
        banner.classList.remove("d-none");
      }
      els.pickBtn.disabled = true;
    } catch (error) {
      console.warn("health check failed", error);
    }
  })();

  window.__batchApp = {
    items,
    els,
    selectItem,
    renderList,
    refreshButtons,
    clearDraft,
    MAX_FILES,
  };
})();
