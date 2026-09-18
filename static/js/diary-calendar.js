(function () {
    "use strict";
    const calendar = document.querySelector("[data-diary-calendar]");
    if (!calendar) return;

    // 日记和健身共用这段脚本，只有存储前缀和计数单位不同。
    const prefix = calendar.dataset.storagePrefix || "diary-calendar";
    const countUnit = calendar.dataset.countUnit || "天";
    const STORAGE_COLLAPSED = prefix + ":collapsed";
    const STORAGE_MODE = prefix + ":mode";
    const collapseButton = calendar.querySelector("[data-calendar-collapse]");
    const modeButtons = Array.from(calendar.querySelectorAll("[data-calendar-mode]"));
    const yearPrevious = calendar.querySelector("[data-year-prev]");
    const yearNext = calendar.querySelector("[data-year-next]");
    const yearLabel = calendar.querySelector("[data-year-label]");
    const yearGrid = calendar.querySelector("[data-year-grid]");
    const yearStatus = calendar.querySelector("[data-year-status]");
    const archiveYear = Number(calendar.dataset.year);
    const archiveMonth = Number(calendar.dataset.month);
    const maxYear = Number(calendar.dataset.maxYear) || archiveYear;
    let shownYear = archiveYear;
    let minYear = 1;
    let controller = null;

    function remember(key, value) {
        try { localStorage.setItem(key, value); } catch (error) { /* private mode */ }
    }

    function syncState() {
        const collapsed = calendar.classList.contains("is-collapsed");
        collapseButton.setAttribute("aria-expanded", String(!collapsed));
        collapseButton.setAttribute("aria-label", collapsed ? "展开日历" : "收起日历");
        collapseButton.title = collapsed ? "展开日历" : "收起日历";
        const yearMode = calendar.classList.contains("is-year");
        modeButtons.forEach(function (button) {
            button.setAttribute("aria-pressed", String((button.dataset.calendarMode === "year") === yearMode));
        });
    }

    syncState();
    // The inline bootstrap applied the stored state without animation; enable transitions after first paint.
    const releaseTransitions = function () { calendar.classList.remove("is-static"); };
    requestAnimationFrame(function () { requestAnimationFrame(releaseTransitions); });
    // Background tabs do not run animation frames, so also release on a timer.
    window.setTimeout(releaseTransitions, 300);

    collapseButton.addEventListener("click", function () {
        const collapsed = calendar.classList.toggle("is-collapsed");
        remember(STORAGE_COLLAPSED, collapsed ? "1" : "0");
        syncState();
    });

    modeButtons.forEach(function (button) {
        button.addEventListener("click", function () {
            const yearMode = button.dataset.calendarMode === "year";
            calendar.classList.toggle("is-year", yearMode);
            remember(STORAGE_MODE, yearMode ? "year" : "month");
            syncState();
        });
    });

    function monthUrl(value) {
        const url = new URL(calendar.dataset.diaryUrl, window.location.origin);
        url.searchParams.set("month", value);
        return url.pathname + url.search;
    }

    function renderOverview(result) {
        shownYear = result.year;
        minYear = result.min_year;
        yearLabel.textContent = result.year + " 年";
        yearPrevious.disabled = result.year <= minYear;
        yearNext.disabled = result.year >= (result.max_year || maxYear);
        const fragment = document.createDocumentFragment();
        result.overview.forEach(function (month) {
            const link = document.createElement("a");
            link.className = "diary-mini-month"
                + (month.future ? " is-future" : "")
                + (result.year === archiveYear && month.month === archiveMonth ? " is-active" : "");
            link.href = monthUrl(month.value);
            if (month.future) {
                link.setAttribute("aria-disabled", "true");
                link.tabIndex = -1;
            }
            const head = document.createElement("span");
            head.className = "diary-mini-month-head";
            const title = document.createElement("b");
            title.textContent = month.label;
            head.appendChild(title);
            if (!month.future) {
                const count = document.createElement("span");
                count.textContent = month.recorded_days + " " + countUnit;
                head.appendChild(count);
            }
            const cells = document.createElement("span");
            cells.className = "diary-mini-month-cells";
            cells.setAttribute("aria-hidden", "true");
            month.cells.forEach(function (cell) {
                const dot = document.createElement("i");
                if (cell) {
                    dot.dataset.level = cell.level;
                    if (cell.today) dot.className = "is-today";
                    else if (cell.future) dot.className = "is-future";
                }
                cells.appendChild(dot);
            });
            link.appendChild(head);
            link.appendChild(cells);
            fragment.appendChild(link);
        });
        yearGrid.replaceChildren(fragment);
        yearGrid.hidden = false;
        yearStatus.hidden = true;
    }

    async function loadYear(year) {
        if (controller) controller.abort();
        controller = new AbortController();
        const activeController = controller;
        const timeout = window.setTimeout(function () { activeController.abort(); }, 15000);
        yearPrevious.disabled = true;
        yearNext.disabled = true;
        yearStatus.hidden = false;
        yearStatus.textContent = "正在读取 " + year + " 年…";
        try {
            const url = new URL(calendar.dataset.endpoint, window.location.origin);
            url.searchParams.set("year", year);
            const response = await fetch(url, {
                headers: { Accept: "application/json" },
                cache: "no-store",
                signal: activeController.signal,
            });
            if (response.status === 401) throw new Error("登录已过期，请重新登录后查看。");
            if (!response.ok) throw new Error("这一年暂时没有加载成功，请再试一次。");
            const result = await response.json();
            if (activeController !== controller) return;
            renderOverview(result);
        } catch (error) {
            if (activeController !== controller) return;
            yearStatus.textContent = error.name === "AbortError" ? "读取超时，请再试一次。" : error.message;
            yearStatus.hidden = false;
            yearPrevious.disabled = shownYear <= minYear;
            yearNext.disabled = shownYear >= maxYear;
        } finally {
            window.clearTimeout(timeout);
        }
    }

    yearPrevious.addEventListener("click", function () { loadYear(shownYear - 1); });
    yearNext.addEventListener("click", function () { loadYear(shownYear + 1); });
})();
