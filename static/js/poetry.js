/**
 * static/js/poetry.js
 * 个人博客诗斋与今日诗笺（Warm Editorial Archive）专用交互脚本
 * 规范：零 Emoji、零赏析、双轨持久化、手势拖选隔离、3D 翻牌与标点分句
 */
(function () {
  "use strict";

  // ==========================================
  // 1. 常量与工具函数
  // ==========================================
  const PUNCT_REGEX = /[，。！？、；：\s\u3000\xa0\u200b,.\!?;:\"'“”‘’（）《》〈〉【】〔〕——……—·]/g;
  const CLAUSE_SPLIT_REGEX = /[^，。！？；]+[，。！？；]?/g;
  const GUEST_STORAGE_KEY = "silver_blog_poetry_guest_v2";

  const DIMENSION_COEFFS = {
    style: 1.2,
    mood: 1.2,
    theme: 1.0,
    dynasty: 0.8
  };

  function getCsrfToken() {
    if (window.BLOG_CSRF_TOKEN) return window.BLOG_CSRF_TOKEN;
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    const match = document.cookie.match(/(?:^|;\s*)(?:csrf_token|_csrf_token)=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function showToast(message) {
    let toast = document.getElementById("toastNotice");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "toastNotice";
      toast.className = "poetry-toast";
      toast.innerHTML = '<span id="toastMessage"></span>';
      document.body.appendChild(toast);
    }
    const msgEl = toast.querySelector("#toastMessage") || toast;
    msgEl.textContent = message;
    toast.classList.add("is-show");
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => {
      toast.classList.remove("is-show");
    }, 2400);
  }

  function splitQuoteToClauses(containerEl, rawText) {
    if (!containerEl || !rawText) return;
    const text = String(rawText).trim();
    const matches = text.match(CLAUSE_SPLIT_REGEX);
    containerEl.innerHTML = "";
    if (matches && matches.length > 0) {
      matches.forEach(clause => {
        const span = document.createElement("span");
        span.className = "poetry-clause";
        span.textContent = clause;
        containerEl.appendChild(span);
      });
    } else {
      const span = document.createElement("span");
      span.className = "poetry-clause";
      span.textContent = text;
      containerEl.appendChild(span);
    }
  }

  function cleanExcerptText(text) {
    if (!text || typeof text !== "string") return "";
    return text.replace(/\s*\r?\n\s*/g, "").trim();
  }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderLineWithMarks(lineText, partialExcerpts) {
    if (!partialExcerpts || partialExcerpts.length === 0) {
      return escapeHtml(lineText);
    }
    const ranges = [];
    partialExcerpts.forEach(excText => {
      if (!excText || excText === lineText) return;
      let startIdx = 0;
      while (startIdx < lineText.length) {
        const idx = lineText.indexOf(excText, startIdx);
        if (idx === -1) break;
        ranges.push([idx, idx + excText.length]);
        startIdx = idx + excText.length;
      }
    });
    if (ranges.length === 0) {
      return escapeHtml(lineText);
    }
    ranges.sort((a, b) => a[0] - b[0] || b[1] - a[1]);
    const merged = [ranges[0]];
    for (let i = 1; i < ranges.length; i++) {
      const prev = merged[merged.length - 1];
      const curr = ranges[i];
      if (curr[0] <= prev[1]) {
        prev[1] = Math.max(prev[1], curr[1]);
      } else {
        merged.push(curr);
      }
    }
    let out = "";
    let cursor = 0;
    merged.forEach(([s, e]) => {
      if (s > cursor) out += escapeHtml(lineText.slice(cursor, s));
      out += `<mark class="verse-inline-mark">${escapeHtml(lineText.slice(s, e))}</mark>`;
      cursor = e;
    });
    if (cursor < lineText.length) out += escapeHtml(lineText.slice(cursor));
    return out;
  }

  // ==========================================
  // 2. 数据层与 API 客户端
  // ==========================================
  class PoetryDataClient {
    constructor(isAuthenticated) {
      this.isAuthenticated = isAuthenticated;
      this.baseUrl = "/api/poetry";
    }

    async _fetch(url, options = {}) {
      const headers = {
        "Content-Type": "application/json",
        "X-CSRF-Token": getCsrfToken(),
        ...(options.headers || {})
      };
      return fetch(url, { ...options, headers });
    }

    async getDataset() {
      try {
        const res = await this._fetch(`${this.baseUrl}/dataset`);
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        if (data.status === "success") {
          try {
            localStorage.setItem("poetry_dataset_cache_v2", JSON.stringify(data));
          } catch (e) {}
          return data;
        }
      } catch (e) {
        try {
          const cached = localStorage.getItem("poetry_dataset_cache_v2");
          if (cached) return JSON.parse(cached);
        } catch (err) {}
      }
      return null;
    }

    async getPreferences() {
      if (!this.isAuthenticated) {
        return this.getLocalPreferences();
      }
      try {
        const res = await this._fetch(`${this.baseUrl}/preferences`);
        if (!res.ok) throw new Error("HTTP " + res.status);
        return await res.json();
      } catch (e) {
        return this.getLocalPreferences();
      }
    }

    getLocalPreferences() {
      try {
        const raw = localStorage.getItem(GUEST_STORAGE_KEY);
        if (raw) return JSON.parse(raw);
      } catch (e) {}
      return {
        liked_poem_ids: [],
        liked_excerpts: [],
        tag_weights: {}
      };
    }

    saveLocalPreferences(prefs) {
      try {
        localStorage.setItem(GUEST_STORAGE_KEY, JSON.stringify(prefs));
      } catch (e) {}
    }

    async togglePoemLike(poem, willLike) {
      const action = willLike ? "like" : "unlike";
      let serverPersisted = false;
      try {
        const res = await this._fetch(`${this.baseUrl}/like`, {
          method: "POST",
          body: JSON.stringify({ poem_id: poem.id, action, tags: poem.tags || {} })
        });
        if (res.ok) {
          const data = await res.json();
          serverPersisted = Boolean(data && data.persisted);
        }
      } catch (e) {
        if (this.isAuthenticated) console.warn("Server like error:", e);
      }

      if (this.isAuthenticated || serverPersisted) {
        try {
          const serverRes = await this._fetch(`${this.baseUrl}/preferences`);
          if (serverRes.ok) return await serverRes.json();
        } catch (e) {}
      }

      const local = this.getLocalPreferences();
      const set = new Set(local.liked_poem_ids || []);
      if (willLike) set.add(poem.id);
      else set.delete(poem.id);
      local.liked_poem_ids = Array.from(set);

      local.tag_weights = local.tag_weights || {};
      if (poem.tags) {
        Object.entries(poem.tags).forEach(([dim, val]) => {
          if (!val) return;
          const delta = (willLike ? 2.0 : -2.0) * (DIMENSION_COEFFS[dim] || 1.0);
          local.tag_weights[val] = Math.max(0, (local.tag_weights[val] || 0) + delta);
        });
      }
      this.saveLocalPreferences(local);
      return local;
    }

    async toggleExcerptLike(poem, text, willLike) {
      const action = willLike ? "like" : "unlike";
      let serverPersisted = false;
      try {
        const res = await this._fetch(`${this.baseUrl}/excerpt_like`, {
          method: "POST",
          body: JSON.stringify({ poem_id: poem.id, text, action, tags: poem.tags || {} })
        });
        if (res.ok) {
          const data = await res.json();
          serverPersisted = Boolean(data && data.persisted);
        }
      } catch (e) {
        if (this.isAuthenticated) console.warn("Server excerpt error:", e);
      }

      if (this.isAuthenticated || serverPersisted) {
        try {
          const serverRes = await this._fetch(`${this.baseUrl}/preferences`);
          if (serverRes.ok) return await serverRes.json();
        } catch (e) {}
      }

      const local = this.getLocalPreferences();
      local.liked_excerpts = local.liked_excerpts || [];
      if (willLike) {
        const exists = local.liked_excerpts.some(item => item.poem_id === poem.id && item.text === text);
        if (!exists) {
          local.liked_excerpts.unshift({
            poem_id: poem.id,
            text,
            poem_title: poem.title,
            title: poem.title,
            poem_author: poem.author,
            author: poem.author,
            dynasty: poem.dynasty,
            timestamp: new Date().toISOString()
          });
        }
      } else {
        local.liked_excerpts = local.liked_excerpts.filter(item => !(item.poem_id === poem.id && item.text === text));
      }

      local.tag_weights = local.tag_weights || {};
      if (poem.tags) {
        Object.entries(poem.tags).forEach(([dim, val]) => {
          if (!val) return;
          const delta = (willLike ? 1.0 : -1.0) * (DIMENSION_COEFFS[dim] || 1.0);
          local.tag_weights[val] = Math.max(0, (local.tag_weights[val] || 0) + delta);
        });
      }
      this.saveLocalPreferences(local);
      return local;
    }

    recordInteraction(poemId, action) {
      if (!this.isAuthenticated) return;
      try {
        this._fetch(`${this.baseUrl}/interaction`, {
          method: "POST",
          body: JSON.stringify({ poem_id: poemId, action })
        }).catch(() => {});
      } catch (e) {}
    }
  }

  // ==========================================
  // 3. 抽样推荐与口味评估算法
  // ==========================================
  function pickNextPoem(pool, currentPoemId, tagWeights) {
    if (!pool || pool.length === 0) return null;
    if (pool.length === 1) return pool[0];

    const candidates = pool.filter(p => p.id !== currentPoemId);
    if (candidates.length === 0) return pool[0];

    const scored = candidates.map(poem => {
      let score = 0;
      if (poem.tags && tagWeights) {
        Object.entries(poem.tags).forEach(([dim, val]) => {
          const w = tagWeights[val] || 0;
          const coeff = DIMENSION_COEFFS[dim] || 1.0;
          score += w * coeff;
        });
      }
      return { poem, score };
    });

    const expScores = scored.map(item => Math.exp(item.score / 2.0));
    const totalExp = expScores.reduce((sum, v) => sum + v, 0);
    const rand = Math.random() * totalExp;

    let accum = 0;
    for (let i = 0; i < scored.length; i++) {
      accum += expScores[i];
      if (rand <= accum) {
        return scored[i].poem;
      }
    }
    return candidates[0];
  }

  function generateTasteDescription(tagWeights, isGuest) {
    if (!tagWeights || Object.keys(tagWeights).length === 0) {
      return "字面澄澈如水洗，意象清丽如画。";
    }
    const entries = Object.entries(tagWeights).filter(([_, w]) => w > 0);
    if (entries.length === 0) {
      return "字面澄澈如水洗，意象清丽如画。";
    }
    entries.sort((a, b) => b[1] - a[1]);
    const topTags = entries.slice(0, 2).map(e => e[0]).join(" · ");
    const guestNotice = isGuest ? "（当前为访客本地暂存）" : "";
    return `近期常驻于「${topTags}」之间。${guestNotice}`;
  }

  // ==========================================
  // 4. 首页侧边栏控制器 (SidebarPoetryCard)
  // ==========================================
  class SidebarPoetryCard {
    constructor(rootEl, apiClient) {
      this.root = rootEl;
      this.api = apiClient;
      this.dataset = null;
      this.currentPoem = null;
      this.likedPoemIds = new Set();
      this.tagWeights = {};

      this.innerGrid = rootEl.querySelector("#sidebarCardInner");
      this.switchBtn = rootEl.querySelector("#sidebarSwitchBtn");
      this.quoteLines = rootEl.querySelector("#sidebarQuoteLines");
      this.authorEl = rootEl.querySelector("#sidebarAuthor");
      this.badgeEl = rootEl.querySelector("#sidebarBadge");
      this.likeBtn = rootEl.querySelector("#sidebarLikeBtn");
      this.backLikeBtn = rootEl.querySelector("#sidebarBackLikeBtn");
      this.backTitle = rootEl.querySelector("#sidebarBackTitle");
      this.backAuthor = rootEl.querySelector("#sidebarBackAuthor");
      this.versesFull = rootEl.querySelector("#sidebarPoemFull");
      this.enterHallLink = rootEl.querySelector("#sidebarEnterHallLink");

      this.isFlipped = false;
      this.pointerStartX = 0;
      this.pointerStartY = 0;

      this.init();
    }

    async init() {
      this.dataset = await this.api.getDataset();
      const prefs = await this.api.getPreferences();
      this.likedPoemIds = new Set(prefs.liked_poem_ids || []);
      this.tagWeights = prefs.tag_weights || {};

      if (this.dataset && this.dataset.poems) {
        const firstId = this.likeBtn ? this.likeBtn.getAttribute("data-poem-id") : null;
        this.currentPoem = this.dataset.poems.find(p => p.id === firstId) || this.dataset.poems[0];
      }

      this.bindEvents();
      if (this.currentPoem) {
        this.render(this.currentPoem);
      }
    }

    bindEvents() {
      if (this.switchBtn) {
        this.switchBtn.addEventListener("click", e => {
          e.stopPropagation();
          this.switchNext();
        });
      }

      const handleLike = async e => {
        e.stopPropagation();
        if (!this.currentPoem) return;
        const willLike = !this.likedPoemIds.has(this.currentPoem.id);
        if (willLike) this.likedPoemIds.add(this.currentPoem.id);
        else this.likedPoemIds.delete(this.currentPoem.id);

        this.updateLikeButtons(willLike);
        showToast(willLike ? "已喜欢此诗" : "已取消喜欢");
        const updated = await this.api.togglePoemLike(this.currentPoem, willLike);
        if (updated && Array.isArray(updated.liked_poem_ids)) {
          this.likedPoemIds = new Set(updated.liked_poem_ids);
          this.updateLikeButtons(this.likedPoemIds.has(this.currentPoem.id));
        }
        if (updated && updated.tag_weights) this.tagWeights = updated.tag_weights;
      };

      if (this.likeBtn) this.likeBtn.addEventListener("click", handleLike);
      if (this.backLikeBtn) this.backLikeBtn.addEventListener("click", handleLike);

      // 翻转按钮专属监听（避免与 pointerup 叠加双触发）
      const flipBtn = this.root.querySelector("#sidebarFlipBtn");
      if (flipBtn) flipBtn.addEventListener("click", e => { e.stopPropagation(); this.toggleFlip(); });
      const flipBackBtn = this.root.querySelector("#sidebarFlipBackBtn");
      if (flipBackBtn) flipBackBtn.addEventListener("click", e => { e.stopPropagation(); this.toggleFlip(); });

      // 纸面热区点击翻转（带手势与选区隔离）
      this.root.querySelectorAll("[data-side-flip-trigger]").forEach(el => {
        el.addEventListener("pointerdown", e => {
          this.pointerStartX = e.clientX;
          this.pointerStartY = e.clientY;
        });

        el.addEventListener("pointerup", e => {
          if (e.target.closest("button, a")) return;
          const dx = Math.abs(e.clientX - this.pointerStartX);
          const dy = Math.abs(e.clientY - this.pointerStartY);
          if (dx > 8 || dy > 8) return;

          const sel = window.getSelection();
          if (sel && sel.toString().trim().length > 0) return;

          this.toggleFlip();
        });
      });
    }

    toggleFlip() {
      this.isFlipped = !this.isFlipped;
      if (this.innerGrid) {
        this.innerGrid.classList.toggle("is-flipped", this.isFlipped);
      }
      if (this.currentPoem) {
        this.api.recordInteraction(this.currentPoem.id, "flip");
      }
    }

    switchNext() {
      if (!this.dataset || !this.dataset.poems) return;
      const next = pickNextPoem(this.dataset.poems, this.currentPoem ? this.currentPoem.id : null, this.tagWeights);
      if (!next) return;
      this.currentPoem = next;
      this.render(next);
      this.api.recordInteraction(next.id, "switch");
      showToast("已呈上新的一阕");
    }

    render(poem) {
      if (!poem) return;

      if (this.quoteLines) {
        splitQuoteToClauses(this.quoteLines, poem.highlight);
      }
      if (this.authorEl) {
        this.authorEl.textContent = `${poem.dynasty} · ${poem.author}〈${poem.cipai || poem.title}〉`;
      }
      if (this.badgeEl) {
        this.badgeEl.hidden = !poem.is_handwritten;
      }

      if (this.backTitle) this.backTitle.textContent = `《${poem.title}》`;
      if (this.backAuthor) this.backAuthor.textContent = `${poem.dynasty} · ${poem.author}`;
      if (this.versesFull) {
        this.versesFull.innerHTML = "";
        (poem.content || []).forEach(line => {
          const p = document.createElement("p");
          p.className = "poetry-side-line";
          p.textContent = line;
          this.versesFull.appendChild(p);
        });
      }

      if (this.enterHallLink) {
        this.enterHallLink.href = `/poetry?poem=${encodeURIComponent(poem.id)}`;
      }

      const isLiked = this.likedPoemIds.has(poem.id);
      this.updateLikeButtons(isLiked);
      if (this.likeBtn) this.likeBtn.setAttribute("data-poem-id", poem.id);
      if (this.backLikeBtn) this.backLikeBtn.setAttribute("data-poem-id", poem.id);
    }

    updateLikeButtons(isLiked) {
      [this.likeBtn, this.backLikeBtn].forEach(btn => {
        if (!btn) return;
        btn.classList.toggle("is-liked", isLiked);
        const label = btn.querySelector(".like-label");
        if (label) label.textContent = isLiked ? "已喜欢" : "喜欢";
      });
    }
  }

  // ==========================================
  // 5. 独立诗斋沉浸页控制器 (PoetryHallApp)
  // ==========================================
  class PoetryHallApp {
    constructor(rootEl, apiClient) {
      this.root = rootEl;
      this.api = apiClient;
      this.dataset = null;
      this.currentPoem = null;
      this.likedPoemIds = new Set();
      this.likedExcerpts = [];
      this.tagWeights = {};

      this.filterState = {
        dim: null,
        tag: null,
        onlyHandwritten: false
      };

      this.innerGrid = rootEl.querySelector("#immersiveCardInner");
      this.btnSwitch = rootEl.querySelector("#btnSwitchPoem");
      this.btnFlip = rootEl.querySelector("#btnFlipCard");
      this.btnLike = rootEl.querySelector("#btnImmLike");
      this.likeText = rootEl.querySelector("#immLikeBtnText");

      this.tasteNoteEl = rootEl.querySelector("#poetryTasteNote");
      this.kpiTotalEl = rootEl.querySelector("#kpiTotalPoems");
      this.kpiLikedPoemsEl = rootEl.querySelector("#kpiLikedPoems");
      this.kpiLikedExcerptsEl = rootEl.querySelector("#kpiLikedExcerpts");

      this.btnFilterAll = rootEl.querySelector("#btnFilterAll");
      this.btnFilterHandwritten = rootEl.querySelector("#btnFilterHandwritten");
      this.filterSummaryText = rootEl.querySelector("#filterSummaryText");
      this.btnFilterClear = rootEl.querySelector("#btnFilterClear");
      this.filterTray = rootEl.querySelector("#filterTray");

      this.genreLabel = rootEl.querySelector("#stageGenreLabel");
      this.handwrittenTag = rootEl.querySelector("#stageHandwrittenTag");
      this.quoteLines = rootEl.querySelector("#stageQuoteLines");
      this.frontAuthor = rootEl.querySelector("#stageFrontAuthor");
      this.frontTags = rootEl.querySelector("#stageFrontTags");

      this.backTitle = rootEl.querySelector("#stageBackTitle");
      this.backAuthor = rootEl.querySelector("#stageBackAuthor");
      this.backVerses = rootEl.querySelector("#stageBackVerses") || rootEl.querySelector("#immFullContent");

      this.tabExcerpts = rootEl.querySelector("#tabExcerpts");
      this.tabPoems = rootEl.querySelector("#tabPoems");
      this.countExcerptsEl = rootEl.querySelector("#countExcerpts");
      this.countPoemsEl = rootEl.querySelector("#countPoems");
      this.paneExcerpts = rootEl.querySelector("#notebookExcerptsList");
      this.panePoems = rootEl.querySelector("#notebookPoemsList");
      this.excerptsBody = rootEl.querySelector("#excerptsListBody");
      this.poemsBody = rootEl.querySelector("#poemsListBody");
      this.excerptsEmptyTip = rootEl.querySelector("#excerptsEmptyTip");
      this.poemsEmptyTip = rootEl.querySelector("#poemsEmptyTip");

      this.popover = rootEl.querySelector("#excerptPopover");
      this.popoverBtn = rootEl.querySelector("#btnPopoverExcerptLike");
      this.popoverBtnText = rootEl.querySelector("#popoverBtnText");
      this.currentSelectionText = "";

      this.isFlipped = false;
      this.pointerStartX = 0;
      this.pointerStartY = 0;
      this._selectionCooldown = 0;

      this.init();
    }

    async init() {
      this.dataset = await this.api.getDataset();
      const prefs = await this.api.getPreferences();
      this.likedPoemIds = new Set(prefs.liked_poem_ids || []);
      this.likedExcerpts = prefs.liked_excerpts || [];
      this.tagWeights = prefs.tag_weights || {};

      if (!this.dataset || !this.dataset.poems) return;

      const params = new URLSearchParams(window.location.search);
      const urlPoemId = params.get("poem");
      const ssrPoemId = this.btnLike ? this.btnLike.getAttribute("data-poem-id") : null;
      if (urlPoemId) {
        this.currentPoem = this.dataset.poems.find(p => p.id === urlPoemId) || this.dataset.poems[0];
      } else if (ssrPoemId) {
        this.currentPoem = this.dataset.poems.find(p => p.id === ssrPoemId) || this.dataset.poems[0];
      } else {
        this.currentPoem = this.dataset.poems[0];
      }

      this.bindEvents();
      this.renderCurrentPoem();
      this.updateOverviewAndKpis();
      this.renderNotebook();
    }

    bindEvents() {
      if (this.btnSwitch) {
        this.btnSwitch.addEventListener("click", () => this.switchNext());
      }

      if (this.btnFlip) {
        this.btnFlip.addEventListener("click", () => this.toggleFlip());
      }

      if (this.btnLike) {
        this.btnLike.addEventListener("click", () => this.toggleCurrentPoemLike());
      }

      // 卡片点击与翻牌手势隔离（抵御移动端 350ms 合成点击及交互元素过滤）
      if (this.innerGrid) {
        this.innerGrid.addEventListener("click", (e) => {
          if (Date.now() - this._selectionCooldown < 350) return;
          const interactive = e.target.closest(
            "button, a, [data-prevent-flip], .poem-reading-line, .back-poem-line, .verse-line, .excerpt-selection-popover, .popover-cinnabar-btn, .verse-line-item, [role='button']"
          );
          if (interactive) return;
          const sel = window.getSelection();
          if (sel && sel.toString().trim().length > 0) return;
          this.toggleFlip();
        });
      }

      // 翻面触发器（支持 data 属性与返回提示类名）
      this.root.querySelectorAll("[data-hall-flip-trigger], .back-flip-return-hint").forEach(el => {
        el.addEventListener("click", e => {
          if (el.tagName !== "BUTTON") {
            if (Date.now() - this._selectionCooldown < 350) return;
            if (e.target.closest("button, a")) return;
            const sel = window.getSelection();
            if (sel && sel.toString().trim().length > 0) return;
          }
          e.stopPropagation();
          this.toggleFlip();
        });
      });

      // 背面诗行点击事件委托（兼容首屏 SSR 节点与切诗后动态节点，不重复绑定）
      if (this.backVerses) {
        this.backVerses.addEventListener("click", (e) => {
          const pLine = e.target.closest(".verse-line-item, .poem-reading-line");
          if (!pLine || !this.backVerses.contains(pLine)) return;
          e.stopPropagation();
          if (Date.now() - this._selectionCooldown < 350) return;
          const sel = window.getSelection();
          if (sel && sel.toString().trim().length > 0) return;
          const lineText = pLine.getAttribute("data-line-text") || pLine.textContent.trim();
          this.toggleLineExcerptLike(lineText);
        });
      }

      if (this.btnFilterAll) {
        this.btnFilterAll.addEventListener("click", () => this.resetFilters());
      }
      if (this.btnFilterClear) {
        this.btnFilterClear.addEventListener("click", () => this.resetFilters());
      }
      if (this.btnFilterHandwritten) {
        this.btnFilterHandwritten.addEventListener("click", () => {
          this.filterState.onlyHandwritten = !this.filterState.onlyHandwritten;
          this.btnFilterHandwritten.classList.toggle("is-active", this.filterState.onlyHandwritten);
          this.btnFilterAll.classList.toggle("is-active", !this.hasActiveFilter());
          this.applyFilter();
        });
      }

      this.root.querySelectorAll("[data-dim-toggle]").forEach(btn => {
        btn.addEventListener("click", () => {
          const dim = btn.getAttribute("data-dim-toggle");
          if (this.filterState.dim === dim && !this.filterTray.hidden) {
            this.filterTray.hidden = true;
          } else {
            this.filterState.dim = dim;
            this.renderFilterTray(dim);
            this.filterTray.hidden = false;
          }
        });
      });

      // 选区捕获与移动端 touchend 处理（严格限定在背面诗句容器内）
      const handleSelectionEnd = () => {
        this.evaluateVerseSelection(true);
      };

      document.addEventListener("selectionchange", () => {
        this.evaluateVerseSelection(false);
      });
      window.addEventListener("scroll", () => {
        if (this.popover && !this.popover.hidden) {
          this.evaluateVerseSelection(false);
        }
      }, { passive: true });
      document.addEventListener("mouseup", handleSelectionEnd);
      document.addEventListener("touchend", handleSelectionEnd);

      // 朱笔圈点墨签点击显式调用 e.stopPropagation() & preventDefault()
      const popoverEl = this.popover || this.root.querySelector(".excerpt-selection-popover");
      if (popoverEl) {
        popoverEl.addEventListener("click", (e) => {
          e.stopPropagation();
          e.preventDefault();
          if (!this.currentSelectionText || !this.currentPoem) return;
          const targetText = this.currentSelectionText;
          this.hidePopover();
          const sel = window.getSelection();
          if (sel) sel.removeAllRanges();
          this.toggleCustomExcerptLike(targetText);
        });
      }

      document.addEventListener("pointerdown", e => {
        if (this.popover && !this.popover.hidden && !this.popover.contains(e.target)) {
          this.hidePopover();
        }
      });

      if (this.tabExcerpts && this.tabPoems) {
        this.tabExcerpts.addEventListener("click", () => {
          this.tabExcerpts.classList.add("is-active");
          this.tabExcerpts.setAttribute("aria-selected", "true");
          this.tabPoems.classList.remove("is-active");
          this.tabPoems.setAttribute("aria-selected", "false");
          this.paneExcerpts.hidden = false;
          this.paneExcerpts.classList.add("is-active");
          this.panePoems.hidden = true;
          this.panePoems.classList.remove("is-active");
        });

        this.tabPoems.addEventListener("click", () => {
          this.tabPoems.classList.add("is-active");
          this.tabPoems.setAttribute("aria-selected", "true");
          this.tabExcerpts.classList.remove("is-active");
          this.tabExcerpts.setAttribute("aria-selected", "false");
          this.panePoems.hidden = false;
          this.panePoems.classList.add("is-active");
          this.paneExcerpts.hidden = true;
          this.paneExcerpts.classList.remove("is-active");
        });
      }

      window.addEventListener("keydown", e => {
        const tag = (e.target.tagName || "").toLowerCase();
        if (tag === "input" || tag === "textarea") return;

        if (e.code === "Space" || e.key === "ArrowRight") {
          e.preventDefault();
          this.switchNext();
        } else if (e.code === "Enter" || e.key === "f" || e.key === "F") {
          e.preventDefault();
          this.toggleFlip();
        } else if (e.key === "l" || e.key === "L") {
          e.preventDefault();
          this.toggleCurrentPoemLike();
        }
      });
    }

    hasActiveFilter() {
      return Boolean(this.filterState.tag || this.filterState.onlyHandwritten);
    }

    renderFilterTray(dim) {
      if (!this.dataset || !this.dataset.tags || !this.dataset.tags[dim]) {
        this.filterTray.hidden = true;
        return;
      }
      this.filterTray.innerHTML = "";
      const tags = this.dataset.tags[dim] || [];
      tags.forEach(tag => {
        const pill = document.createElement("button");
        pill.className = "poetry-filter-tag-pill";
        pill.type = "button";
        pill.textContent = tag;
        if (this.filterState.tag === tag) {
          pill.classList.add("is-selected");
        }
        pill.addEventListener("click", () => {
          if (this.filterState.tag === tag) {
            this.filterState.tag = null;
            pill.classList.remove("is-selected");
          } else {
            this.filterState.tag = tag;
            this.filterTray.querySelectorAll(".poetry-filter-tag-pill").forEach(p => p.classList.remove("is-selected"));
            pill.classList.add("is-selected");
          }
          this.btnFilterAll.classList.toggle("is-active", !this.hasActiveFilter());
          this.applyFilter();
        });
        this.filterTray.appendChild(pill);
      });
    }

    resetFilters() {
      this.filterState = { dim: null, tag: null, onlyHandwritten: false };
      this.filterTray.hidden = true;
      if (this.btnFilterAll) this.btnFilterAll.classList.add("is-active");
      if (this.btnFilterHandwritten) this.btnFilterHandwritten.classList.remove("is-active");
      this.root.querySelectorAll("[data-dim-toggle]").forEach(b => b.classList.remove("is-active"));
      if (this.filterSummaryText) this.filterSummaryText.textContent = "";
      if (this.btnFilterClear) this.btnFilterClear.hidden = true;
      this.applyFilter();
    }

    applyFilter() {
      if (!this.dataset || !this.dataset.poems) return;
      let pool = this.dataset.poems;

      if (this.filterState.onlyHandwritten) {
        pool = pool.filter(p => p.is_handwritten);
      }
      if (this.filterState.tag) {
        pool = pool.filter(p => {
          if (!p.tags) return false;
          return Object.values(p.tags).includes(this.filterState.tag);
        });
      }

      if (this.hasActiveFilter()) {
        if (this.filterSummaryText) this.filterSummaryText.textContent = `匹配 ${pool.length} 阕`;
        if (this.btnFilterClear) this.btnFilterClear.hidden = false;
      } else {
        if (this.filterSummaryText) this.filterSummaryText.textContent = "";
        if (this.btnFilterClear) this.btnFilterClear.hidden = true;
      }

      if (pool.length > 0 && (!this.currentPoem || !pool.some(p => p.id === this.currentPoem.id))) {
        this.currentPoem = pool[0];
        this.renderCurrentPoem();
      }
    }

    toggleFlip() {
      this.isFlipped = !this.isFlipped;
      if (this.innerGrid) {
        this.innerGrid.classList.toggle("is-flipped", this.isFlipped);
      }
      if (this.btnFlip) {
        this.btnFlip.textContent = this.isFlipped ? "返回词眼" : "展卷全篇";
      }
      if (this.currentPoem) {
        this.api.recordInteraction(this.currentPoem.id, "flip");
      }
      this.hidePopover();
    }

    switchNext() {
      if (!this.dataset || !this.dataset.poems) return;
      let pool = this.dataset.poems;
      if (this.filterState.onlyHandwritten) pool = pool.filter(p => p.is_handwritten);
      if (this.filterState.tag) {
        pool = pool.filter(p => p.tags && Object.values(p.tags).includes(this.filterState.tag));
      }

      const next = pickNextPoem(pool, this.currentPoem ? this.currentPoem.id : null, this.tagWeights);
      if (!next) return;
      this.currentPoem = next;
      this.renderCurrentPoem();
      this.api.recordInteraction(next.id, "switch");
      showToast("已呈上新的一阕");
    }

    renderCurrentPoem() {
      const poem = this.currentPoem;
      if (!poem) return;

      if (this.genreLabel) this.genreLabel.textContent = `${poem.dynasty} · ${poem.cipai || poem.title}`;
      if (this.handwrittenTag) this.handwrittenTag.hidden = !poem.is_handwritten;
      if (this.quoteLines) splitQuoteToClauses(this.quoteLines, poem.highlight);
      if (this.frontAuthor) this.frontAuthor.textContent = `${poem.dynasty} · ${poem.author}《${poem.title}》`;

      if (this.frontTags) {
        this.frontTags.innerHTML = "";
        if (poem.tags) {
          Object.entries(poem.tags).forEach(([dim, val]) => {
            const btn = document.createElement("button");
            btn.className = "poetry-mini-tag";
            btn.type = "button";
            btn.textContent = `# ${val}`;
            btn.addEventListener("click", e => {
              e.stopPropagation();
              this.filterState.dim = dim;
              this.filterState.tag = val;
              this.btnFilterAll.classList.remove("is-active");
              this.renderFilterTray(dim);
              this.filterTray.hidden = false;
              this.applyFilter();
            });
            this.frontTags.appendChild(btn);
          });
        }
      }

      if (this.backTitle) this.backTitle.textContent = `《${poem.title}》`;
      if (this.backAuthor) this.backAuthor.textContent = `${poem.dynasty} · ${poem.author}`;
      this.renderBackVerses();

      const isLiked = this.likedPoemIds.has(poem.id);
      if (this.btnLike) {
        this.btnLike.setAttribute("data-poem-id", poem.id);
        this.btnLike.classList.toggle("is-liked", isLiked);
        if (this.likeText) this.likeText.textContent = isLiked ? "已喜欢整首" : "喜欢整首";
      }
    }

    renderBackVerses() {
      if (!this.backVerses || !this.currentPoem) return;
      this.backVerses.innerHTML = "";
      const lines = this.currentPoem.content || [];
      const poemExcerpts = this.likedExcerpts
        .filter(item => item.poem_id === this.currentPoem.id)
        .map(item => item.text || "")
        .filter(Boolean);

      lines.forEach((line, index) => {
        const pLine = document.createElement("div");
        pLine.className = "poem-reading-line verse-line verse-line-item";
        pLine.setAttribute("data-line-index", String(index));
        pLine.setAttribute("data-line-text", line);

        const isFullMarked = this.isLineLiked(this.currentPoem.id, line);
        const partialExcerpts = poemExcerpts.filter(t => t !== line && line.includes(t));
        if (isFullMarked) {
          pLine.classList.add("is-marked", "is-excerpt-liked", "is-liked");
        }

        const renderedLineHtml = renderLineWithMarks(line, partialExcerpts);
        pLine.innerHTML = `<span class="verse-line-dot" aria-hidden="true"></span><span class="verse-line-text">${renderedLineHtml}</span>`;
        this.backVerses.appendChild(pLine);
      });
    }

    isLineLiked(poemId, lineText) {
      const cleanLine = lineText.replace(PUNCT_REGEX, "").trim();
      if (!cleanLine) return false;
      return this.likedExcerpts.some(item => {
        if (item.poem_id !== poemId) return false;
        const cleanExc = (item.text || "").replace(PUNCT_REGEX, "").trim();
        return cleanExc === cleanLine;
      });
    }

    isExactExcerptLiked(poemId, text) {
      const cleanTarget = cleanExcerptText(text).replace(PUNCT_REGEX, "").trim();
      if (!cleanTarget) return false;
      return this.likedExcerpts.some(item => {
        if (item.poem_id !== poemId) return false;
        const cleanExc = (item.text || "").replace(PUNCT_REGEX, "").trim();
        return cleanExc === cleanTarget;
      });
    }

    findMatchingExcerptText(poemId, text) {
      const cleanTarget = cleanExcerptText(text).replace(PUNCT_REGEX, "").trim();
      const found = this.likedExcerpts.find(item => {
        if (item.poem_id !== poemId) return false;
        const cleanExc = (item.text || "").replace(PUNCT_REGEX, "").trim();
        return cleanExc === cleanTarget;
      });
      return found ? found.text : text;
    }

    async toggleCurrentPoemLike() {
      if (!this.currentPoem) return;
      const willLike = !this.likedPoemIds.has(this.currentPoem.id);
      if (willLike) this.likedPoemIds.add(this.currentPoem.id);
      else this.likedPoemIds.delete(this.currentPoem.id);

      if (this.btnLike) {
        this.btnLike.classList.toggle("is-liked", willLike);
        if (this.likeText) this.likeText.textContent = willLike ? "已喜欢整首" : "喜欢整首";
      }
      showToast(willLike ? "已将此篇收入私藏" : "已移出私藏");

      const updated = await this.api.togglePoemLike(this.currentPoem, willLike);
      if (updated && Array.isArray(updated.liked_poem_ids)) {
        this.likedPoemIds = new Set(updated.liked_poem_ids);
      }
      if (updated && updated.tag_weights) this.tagWeights = updated.tag_weights;
      this.renderCurrentPoem();
      this.updateOverviewAndKpis();
      this.renderNotebook();
    }

    async toggleLineExcerptLike(lineText) {
      if (!this.currentPoem) return;
      const isAlready = this.isLineLiked(this.currentPoem.id, lineText);
      const willLike = !isAlready;
      const targetText = willLike ? lineText : this.findMatchingExcerptText(this.currentPoem.id, lineText);

      showToast(willLike ? "已将本句标入朱砂旁批" : "已移出朱砂旁批");
      const updated = await this.api.toggleExcerptLike(this.currentPoem, targetText, willLike);
      this.likedExcerpts = (updated && updated.liked_excerpts) ? updated.liked_excerpts : [];
      if (updated && updated.tag_weights) this.tagWeights = updated.tag_weights;

      this.renderBackVerses();
      this.updateOverviewAndKpis();
      this.renderNotebook();
    }

    async toggleCustomExcerptLike(excerptText) {
      if (!this.currentPoem || !excerptText) return;
      const cleaned = cleanExcerptText(excerptText);
      const isAlready = this.isExactExcerptLiked(this.currentPoem.id, cleaned);
      const willLike = !isAlready;
      const targetText = willLike ? cleaned : this.findMatchingExcerptText(this.currentPoem.id, cleaned);

      showToast(willLike ? "已将片语摘入朱砂旁批" : "已移出朱砂旁批");
      const updated = await this.api.toggleExcerptLike(this.currentPoem, targetText, willLike);
      this.likedExcerpts = (updated && updated.liked_excerpts) ? updated.liked_excerpts : [];
      if (updated && updated.tag_weights) this.tagWeights = updated.tag_weights;

      this.renderBackVerses();
      this.updateOverviewAndKpis();
      this.renderNotebook();
    }

    isSelectionInsideVerses(sel) {
      if (!this.isFlipped || !this.backVerses || !sel || sel.isCollapsed || sel.rangeCount === 0) {
        return false;
      }
      const range = sel.getRangeAt(0);
      const anchorEl = sel.anchorNode && sel.anchorNode.nodeType === 3 ? sel.anchorNode.parentNode : sel.anchorNode;
      const focusEl = sel.focusNode && sel.focusNode.nodeType === 3 ? sel.focusNode.parentNode : sel.focusNode;
      const commonEl = range.commonAncestorContainer && range.commonAncestorContainer.nodeType === 3
        ? range.commonAncestorContainer.parentNode
        : range.commonAncestorContainer;
      return Boolean(
        anchorEl && focusEl && commonEl &&
        this.backVerses.contains(anchorEl) &&
        this.backVerses.contains(focusEl) &&
        this.backVerses.contains(commonEl)
      );
    }

    isValidPoemExcerpt(cleaned) {
      if (!this.currentPoem || !cleaned) return false;
      const pureChinese = cleaned.replace(PUNCT_REGEX, "").trim();
      if (pureChinese.length < 2) return false;
      const fullText = (this.currentPoem.content || []).join("");
      if (fullText.includes(cleaned)) return true;
      const normFull = fullText.replace(PUNCT_REGEX, "");
      return normFull.includes(pureChinese);
    }

    evaluateVerseSelection(isPointerEnd) {
      const sel = window.getSelection();
      if (!this.isSelectionInsideVerses(sel)) {
        this.hidePopover();
        return;
      }

      const cleaned = cleanExcerptText(sel.toString());
      if (!this.isValidPoemExcerpt(cleaned)) {
        this.hidePopover();
        return;
      }

      if (isPointerEnd) {
        this._selectionCooldown = Date.now();
      }

      const range = sel.getRangeAt(0);
      const rect = range.getBoundingClientRect();
      this.currentSelectionText = cleaned;
      const alreadyLiked = this.isExactExcerptLiked(this.currentPoem.id, cleaned);
      if (this.popoverBtnText) {
        this.popoverBtnText.textContent = alreadyLiked ? "移出旁批" : "摘入旁批";
      }

      if (rect.width > 0 && rect.height > 0) {
        this.showPopover(rect);
      } else if (isPointerEnd && this.backVerses) {
        const fallbackRect = this.backVerses.getBoundingClientRect();
        this.showPopover(fallbackRect);
      } else {
        this.hidePopover();
      }
    }

    showPopover(rect) {
      if (!this.popover) return;
      const top = Math.max(44, rect.top - 6);
      const left = Math.min(window.innerWidth - 64, Math.max(64, rect.left + rect.width / 2));
      this.popover.style.top = `${top}px`;
      this.popover.style.left = `${left}px`;
      this.popover.hidden = false;
      this.popover.classList.add("is-visible");
      this.popover.setAttribute("aria-hidden", "false");
    }

    hidePopover() {
      if (this.popover) {
        this.popover.hidden = true;
        this.popover.classList.remove("is-visible");
        this.popover.setAttribute("aria-hidden", "true");
      }
      this.currentSelectionText = "";
    }

    updateOverviewAndKpis() {
      if (this.kpiLikedPoemsEl) this.kpiLikedPoemsEl.textContent = String(this.likedPoemIds.size);
      if (this.kpiLikedExcerptsEl) this.kpiLikedExcerptsEl.textContent = String(this.likedExcerpts.length);
      if (this.countExcerptsEl) this.countExcerptsEl.textContent = String(this.likedExcerpts.length);
      if (this.countPoemsEl) this.countPoemsEl.textContent = String(this.likedPoemIds.size);

      if (this.tasteNoteEl) {
        this.tasteNoteEl.textContent = generateTasteDescription(this.tagWeights, !this.api.isAuthenticated);
      }
    }

    renderNotebook() {
      if (this.excerptsBody) {
        this.excerptsBody.innerHTML = "";
        if (this.likedExcerpts.length === 0) {
          if (this.excerptsEmptyTip) this.excerptsEmptyTip.hidden = false;
        } else {
          if (this.excerptsEmptyTip) this.excerptsEmptyTip.hidden = true;
          this.likedExcerpts.forEach(item => {
            const poemMeta = (this.dataset && this.dataset.poems)
              ? this.dataset.poems.find(x => x.id === item.poem_id)
              : null;
            const resolvedTitle = item.poem_title || item.title || (poemMeta && poemMeta.title) || "诗篇";
            const resolvedAuthor = item.poem_author || item.author || (poemMeta && poemMeta.author) || "";

            const art = document.createElement("article");
            art.className = "notebook-item";
            art.setAttribute("data-poem-id", item.poem_id || "");
            art.setAttribute("data-excerpt-text", item.text || "");
            art.innerHTML = `
              <div class="notebook-item-main" role="button" tabindex="0" title="在上方卡片中查看此诗">
                <span class="cinnabar-dot" aria-hidden="true"></span>
                <p class="notebook-item-quote">${escapeHtml(item.text)}</p>
                <span class="notebook-item-source">〈${escapeHtml(resolvedTitle)}〉${escapeHtml(resolvedAuthor)}</span>
              </div>
              <button class="poetry-text-btn is-faint btn-remove-excerpt" type="button">移出</button>
            `;

            art.querySelector(".notebook-item-main").addEventListener("click", () => {
              if (this.dataset && this.dataset.poems) {
                const p = this.dataset.poems.find(x => x.id === item.poem_id);
                if (p) {
                  this.currentPoem = p;
                  this.renderCurrentPoem();
                  if (!this.isFlipped) this.toggleFlip();
                  this.root.scrollIntoView({ behavior: "smooth", block: "start" });
                }
              }
            });

            art.querySelector("button").addEventListener("click", async e => {
              e.stopPropagation();
              const p = (this.dataset && this.dataset.poems)
                ? (this.dataset.poems.find(x => x.id === item.poem_id) || { id: item.poem_id, tags: item.tags || {} })
                : (this.currentPoem || { id: item.poem_id, tags: {} });
              const updated = await this.api.toggleExcerptLike(p, item.text, false);
              this.likedExcerpts = (updated && updated.liked_excerpts) ? updated.liked_excerpts : [];
              if (updated && updated.tag_weights) this.tagWeights = updated.tag_weights;
              this.renderBackVerses();
              this.updateOverviewAndKpis();
              this.renderNotebook();
              showToast("已移出朱砂旁批");
            });

            this.excerptsBody.appendChild(art);
          });
        }
      }

      if (this.poemsBody && this.dataset && this.dataset.poems) {
        this.poemsBody.innerHTML = "";
        const likedList = this.dataset.poems.filter(p => this.likedPoemIds.has(p.id));
        if (likedList.length === 0) {
          if (this.poemsEmptyTip) this.poemsEmptyTip.hidden = false;
        } else {
          if (this.poemsEmptyTip) this.poemsEmptyTip.hidden = true;
          likedList.forEach(p => {
            const art = document.createElement("article");
            art.className = "notebook-item";
            art.setAttribute("data-poem-id", p.id);
            art.innerHTML = `
              <div class="notebook-item-main" role="button" tabindex="0" title="在上方卡片中展读此诗">
                <span class="cinnabar-dot" aria-hidden="true"></span>
                <p class="notebook-item-quote">《${escapeHtml(p.title)}》</p>
                <span class="notebook-item-source">${escapeHtml(p.dynasty)} · ${escapeHtml(p.author)}</span>
              </div>
              <button class="poetry-text-btn is-faint btn-remove-poem" type="button">移出</button>
            `;

            art.querySelector(".notebook-item-main").addEventListener("click", () => {
              this.currentPoem = p;
              this.renderCurrentPoem();
              if (this.isFlipped) this.toggleFlip();
              this.root.scrollIntoView({ behavior: "smooth", block: "start" });
            });

            art.querySelector("button").addEventListener("click", async e => {
              e.stopPropagation();
              this.likedPoemIds.delete(p.id);
              const updated = await this.api.togglePoemLike(p, false);
              if (updated && Array.isArray(updated.liked_poem_ids)) {
                this.likedPoemIds = new Set(updated.liked_poem_ids);
              }
              if (updated && updated.tag_weights) this.tagWeights = updated.tag_weights;
              this.renderCurrentPoem();
              this.updateOverviewAndKpis();
              this.renderNotebook();
              showToast("已移出全篇私藏");
            });

            this.poemsBody.appendChild(art);
          });
        }
      }
    }
  }

  // ==========================================
  // 6. 模块入口挂载
  // ==========================================
  document.addEventListener("DOMContentLoaded", () => {
    const sidebarEl = document.getElementById("sidebarPoetryCard");
    if (sidebarEl) {
      const isAuth = sidebarEl.getAttribute("data-authenticated") === "true";
      const apiClient = new PoetryDataClient(isAuth);
      new SidebarPoetryCard(sidebarEl, apiClient);
    }

    const hallEl = document.getElementById("poetryHall");
    if (hallEl) {
      const isAuth = hallEl.getAttribute("data-authenticated") === "true";
      const apiClient = new PoetryDataClient(isAuth);
      new PoetryHallApp(hallEl, apiClient);
    }
  });
})();
