(function () {
    "use strict";
    const calendar = document.querySelector("[data-diary-calendar]");
    if (!calendar) return;
    const toggle = calendar.querySelector(".diary-calendar-toggle");
    const panel = calendar.querySelector(".diary-activity-panel");
    const viewport = calendar.querySelector("[data-activity-viewport]");
    const grid = calendar.querySelector("[data-activity-grid]");
    const months = calendar.querySelector("[data-activity-months]");
    const chart = calendar.querySelector("[data-activity-chart]");
    const footer = calendar.querySelector("[data-activity-footer]");
    const status = calendar.querySelector("[data-activity-status]");
    const retry = calendar.querySelector("[data-activity-retry]");
    const previous = calendar.querySelector("[data-activity-prev]");
    const next = calendar.querySelector("[data-activity-next]");
    const detail = calendar.querySelector("[data-activity-detail]");
    const link = calendar.querySelector("[data-activity-link]");
    const yearLabel = calendar.querySelector("[data-activity-year]");
    const summary = calendar.querySelector("[data-activity-summary]");
    const mobile = window.matchMedia("(max-width: 767px)");
    let data = null;
    let selected = null;
    let pendingYear = Number(calendar.dataset.year);
    let requestNumber = 0;
    let controller = null;

    toggle.disabled = false;

    function isOpen() { return !panel.hidden; }

    function close(restoreFocus) {
        panel.hidden = true;
        toggle.setAttribute("aria-expanded", "false");
        calendar.classList.remove("is-open");
        if (restoreFocus) toggle.focus();
    }

    function sizeCells(scrollToSelection) {
        if (!data || !isOpen()) return;
        if (scrollToSelection && selected) {
            const button = grid.querySelector('[data-date="' + selected.date + '"]');
            if (button) {
                // Show the selected week at the right edge of the mobile window.
                viewport.scrollLeft = Math.max(0, button.offsetLeft - grid.offsetLeft + button.offsetWidth - viewport.clientWidth + 8);
            }
        }
    }

    function select(day, focus) {
        const old = grid.querySelector('[aria-pressed="true"]');
        if (old) { old.setAttribute("aria-pressed", "false"); old.tabIndex = -1; }
        selected = day;
        const button = grid.querySelector('[data-date="' + day.date + '"]');
        if (button) {
            button.setAttribute("aria-pressed", "true");
            button.tabIndex = 0;
            if (focus) button.focus({ preventScroll: true });
        }
        detail.textContent = day.date.slice(5).replace("-", "/") + " · " + (day.count ? day.count + "字" : "未记录");
        detail.title = day.label;
        const editor = document.getElementById("diary-content");
        const writeToday = day.today && !day.count;
        link.hidden = !day.url && !writeToday;
        link.href = day.url || (editor ? "#diary-editor" : "/diary#diary-editor");
        const text = writeToday ? "写下今天" : "查看日记";
        link.querySelector("[data-activity-link-label]").textContent = text;
        link.setAttribute("aria-label", text + "，" + day.label);
    }

    function render(result) {
        data = result;
        chart.hidden = false;
        footer.hidden = false;
        status.hidden = true;
        retry.hidden = true;
        yearLabel.textContent = result.year + "年";
        summary.textContent = "已记录 " + result.recorded_days + " 天";
        previous.disabled = result.year <= result.min_year;
        next.disabled = result.year >= result.max_year;
        panel.style.setProperty("--activity-weeks", result.weeks);
        grid.replaceChildren();
        months.replaceChildren();
        result.months.forEach(function (month) {
            const label = document.createElement("span");
            label.textContent = month.label;
            label.style.setProperty("--activity-column", month.column);
            months.appendChild(label);
        });
        const cells = document.createDocumentFragment();
        result.days.forEach(function (day, index) {
            if (!day) {
                const blank = document.createElement("span");
                blank.className = "diary-activity-placeholder";
                blank.setAttribute("aria-hidden", "true");
                cells.appendChild(blank);
                return;
            }
            const cell = document.createElement("button");
            cell.type = "button";
            cell.className = "diary-activity-day" + (day.today ? " is-today" : "") + (day.future ? " is-future" : "");
            cell.dataset.level = day.level;
            cell.dataset.date = day.date;
            cell.dataset.index = index;
            cell.title = day.label;
            cell.setAttribute("aria-label", day.label);
            cell.setAttribute("aria-pressed", "false");
            cell.tabIndex = -1;
            cell.disabled = day.future;
            cells.appendChild(cell);
        });
        grid.appendChild(cells);
        const available = result.days.filter(function (day) { return day && !day.future; });
        const latest = available.filter(function (day) { return day.count; }).pop();
        const today = available.find(function (day) { return day.today; });
        select(today || latest || available[available.length - 1], false);
        requestAnimationFrame(function () { sizeCells(true); });
    }

    async function loadYear(year) {
        pendingYear = year;
        const number = ++requestNumber;
        if (controller) controller.abort();
        controller = new AbortController();
        const activeController = controller;
        const timeout = window.setTimeout(function () { activeController.abort(); }, 15000);
        panel.setAttribute("aria-busy", "true");
        previous.disabled = true;
        next.disabled = true;
        chart.hidden = true;
        footer.hidden = true;
        retry.hidden = true;
        summary.textContent = "";
        status.hidden = false;
        status.textContent = "正在读取日记足迹…";
        try {
            const url = new URL(calendar.dataset.endpoint, window.location.origin);
            url.searchParams.set("year", year);
            const response = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store", signal: controller.signal });
            if (response.status === 401) throw new Error("登录已过期，请重新登录后查看。");
            if (!response.ok) throw new Error("足迹暂时没有加载成功，请重试。");
            const result = await response.json();
            if (number !== requestNumber) return;
            render(result);
        } catch (error) {
            if (number !== requestNumber) return;
            status.textContent = error.name === "AbortError" ? "读取超时，请重试。" : error.message;
            status.hidden = false;
            retry.hidden = false;
            if (data) {
                previous.disabled = data.year <= data.min_year;
                next.disabled = data.year >= data.max_year;
            }
        } finally {
            window.clearTimeout(timeout);
            if (number === requestNumber) panel.removeAttribute("aria-busy");
        }
    }

    toggle.addEventListener("click", function () {
        if (isOpen()) { close(false); return; }
        panel.hidden = false;
        toggle.setAttribute("aria-expanded", "true");
        calendar.classList.add("is-open");
        if (!data || !retry.hidden) loadYear(pendingYear);
        else requestAnimationFrame(function () { sizeCells(true); });
    });
    document.addEventListener("pointerdown", function (event) {
        if (isOpen() && !mobile.matches && !calendar.contains(event.target)) close(false);
    });
    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && isOpen()) { event.preventDefault(); close(true); }
    });
    calendar.addEventListener("focusout", function (event) {
        if (isOpen() && !mobile.matches && event.relatedTarget && !calendar.contains(event.relatedTarget)) close(false);
    });
    previous.addEventListener("click", function () { if (data) loadYear(data.year - 1); });
    next.addEventListener("click", function () { if (data) loadYear(data.year + 1); });
    retry.addEventListener("click", function () { loadYear(pendingYear); });
    grid.addEventListener("click", function (event) {
        const button = event.target.closest("[data-index]");
        if (button && !button.disabled) select(data.days[Number(button.dataset.index)], false);
    });
    grid.addEventListener("keydown", function (event) {
        const button = event.target.closest("[data-index]");
        if (!button || !data) return;
        const moves = { ArrowLeft: -7, ArrowRight: 7, ArrowUp: -1, ArrowDown: 1 };
        let index = Number(button.dataset.index);
        if (Object.prototype.hasOwnProperty.call(moves, event.key)) index += moves[event.key];
        else if (event.key === "Home") index = data.days.findIndex(function (day) { return day && !day.future; });
        else if (event.key === "End") index = data.days.reduce(function (last, day, i) { return day && !day.future ? i : last; }, 0);
        else return;
        event.preventDefault();
        const day = data.days[index];
        if (day && !day.future) {
            select(day, true);
            const cell = grid.querySelector('[data-date="' + day.date + '"]');
            const cellRect = cell.getBoundingClientRect();
            const viewRect = viewport.getBoundingClientRect();
            if (cellRect.left < viewRect.left) viewport.scrollLeft -= viewRect.left - cellRect.left + 4;
            if (cellRect.right > viewRect.right) viewport.scrollLeft += cellRect.right - viewRect.right + 4;
        }
    });
    link.addEventListener("click", function (event) {
        if (link.getAttribute("href") === "#diary-editor") {
            event.preventDefault();
            close(false);
            document.getElementById("diary-content").focus();
        }
    });
    window.addEventListener("resize", function () { sizeCells(true); });
})();
