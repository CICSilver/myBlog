(function () {
    "use strict";

    // 动作的记法决定表格形态。录入时不选，跟着动作走。
    const KINDS = {
        深蹲: "bilateral", 臀桥: "bilateral", 提踵: "bilateral", 侧平举: "bilateral",
        弯举: "unilateral", 划船: "unilateral", 卧推: "unilateral", 抬腕: "unilateral",
        平板支撑: "static",
    };

    // RPE 说的是“还剩几次没做”，比“累不累”这种主观说法可判断。
    const RPE_HINTS = {
        1: "极轻 · 几乎不费力",
        2: "很轻 · 热身强度",
        3: "轻松 · 还能再做很多次",
        4: "偏轻 · 还能再做 6 次以上",
        5: "中等 · 还能再做 5～6 次",
        6: "稍累 · 还能再做 4 次",
        7: "有点吃力 · 还能再做 3 次",
        8: "吃力 · 还能再做 2 次",
        9: "很吃力 · 还能再做 1 次",
        10: "力竭 · 一次也加不动",
    };

    const CHECK_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 13 4 4L19 7"></path></svg>';
    const REMOVE_BTN = '<button class="fit-set-remove" type="button" data-remove-set'
        + ' aria-label="删除这一组" title="删除这一组">×</button>';
    function noteInput(value) {
        return '<textarea class="fit-set-note" data-field="note" rows="1" maxlength="120"'
            + ' placeholder="这一组的备注" aria-label="这一组的备注">' + escapeHTML(value || "") + "</textarea>";
    }

    function escapeHTML(text) {
        return String(text).replace(/[&<>"']/g, function (ch) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
        });
    }
    const TRASH_SVG = '<svg class="diary-icon" viewBox="0 0 24 24" aria-hidden="true">'
        + '<path d="M3 6h18M8 6V4h8v2M19 6l-1 15H6L5 6M10 11v5M14 11v5"></path></svg>';

    function number(value) {
        const text = String(value == null ? "" : value).trim();
        if (!text) return null;
        const parsed = Number(text);
        return Number.isFinite(parsed) ? parsed : null;
    }

    function format(value) {
        if (value == null) return "—";
        return Number.isInteger(value) ? String(value) : value.toFixed(1);
    }

    // ---------------------------------------------------------------- 图表 ----
    (function chart() {
        const figure = document.querySelector(".fit-chart-figure");
        if (!figure) return;
        const tip = figure.querySelector("[data-chart-tip]");
        const volume = tip.querySelector("[data-tip-vol]");
        const meta = tip.querySelector("[data-tip-meta]");

        figure.querySelectorAll(".fit-chart-hit").forEach(function (hit) {
            hit.addEventListener("mousemove", function (event) {
                const empty = hit.dataset.vol === "—";
                volume.textContent = empty ? "未训练" : hit.dataset.vol;
                meta.textContent = empty
                    ? hit.dataset.date
                    : hit.dataset.date + " · " + hit.dataset.part + " · " + hit.dataset.sets + " 组";
                const box = figure.getBoundingClientRect();
                const half = tip.offsetWidth / 2 + 4;
                tip.style.left = Math.min(Math.max(event.clientX - box.left, half), box.width - half) + "px";
                tip.style.top = Math.max(event.clientY - box.top - 12, tip.offsetHeight) + "px";
                tip.classList.add("is-on");
            });
        });
        figure.addEventListener("mouseleave", function () { tip.classList.remove("is-on"); });

        const card = document.querySelector(".fit-volume-chart");
        const keys = card.querySelectorAll(".fit-chart-key");
        keys.forEach(function (key) {
            key.addEventListener("click", function () {
                const on = key.getAttribute("aria-pressed") === "true";
                const othersOn = Array.prototype.some.call(keys, function (other) {
                    return other !== key && other.getAttribute("aria-pressed") === "true";
                });
                if (on && !othersOn) return;  // 不留一张空图
                key.setAttribute("aria-pressed", on ? "false" : "true");
                card.classList.toggle("hide-" + key.dataset.series, on);
            });
        });
    })();

    // ------------------------------------------------------------ 侧栏吸附 ----
    /* 侧栏比视口高，只写 top 的 sticky 会把它钉死在顶部，下半截要等主栏
       滚到底才露出来；把单块面板拎出来单独吸附，它又会浮在兄弟面板上面
       把它们“吃掉”。这里整列作为一个整体位移：

         向下滚 —— 跟着页面往上走，直到底边够到视口底部才停住；
         向上滚 —— 立刻松开往下走，直到顶边够到视口顶部才停住。

       也就是往哪个方向滚，就先把那个方向上的内容交出来。只维护一个量：
       内层相对外层顶部的偏移，钳在 [0, 外层高 - 内层高] 之间，保证它
       永远不会跑出自己那一列。 */
    (function stickySide() {
        const container = document.querySelector(".fit-side");
        const inner = document.querySelector(".fit-side-inner");
        if (!container || !inner) return;
        // 会随滚动方向改变位置的东西对一部分人来说是干扰；那就干脆不动，
        // 侧栏退化成普通内容，照样看得全。
        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

        const GAP = 16;
        let offset = 0;
        let lastY = window.scrollY;
        let queued = false;

        function apply() {
            queued = false;
            const y = window.scrollY;
            const delta = y - lastY;
            lastY = y;

            const room = container.offsetHeight - inner.offsetHeight;
            if (room <= 0) {          // 单栏布局或内容变短了
                inner.style.transform = "";
                offset = 0;
                return;
            }

            // 用外层量位置：内层带着 transform，它的 rect 会把偏移算进去。
            const containerTop = container.getBoundingClientRect().top + y;
            const natural = containerTop - y + offset;
            const height = inner.offsetHeight;
            let target;
            if (height + GAP * 2 <= window.innerHeight) {
                target = GAP;                                        // 装得下就钉顶
            } else if (delta > 0) {
                target = Math.max(natural, window.innerHeight - GAP - height);
            } else if (delta < 0) {
                target = Math.min(natural, GAP);
            } else {
                target = natural;
            }

            offset = Math.min(Math.max(offset + (target - natural), 0), room);
            inner.style.transform = offset ? "translate3d(0," + offset + "px,0)" : "";
        }

        function schedule() {
            if (queued) return;
            queued = true;
            window.requestAnimationFrame(apply);
        }

        window.addEventListener("scroll", schedule, { passive: true });
        window.addEventListener("resize", function () {
            offset = 0;
            inner.style.transform = "";
            lastY = window.scrollY;
            apply();
        });
        apply();
    })();

    // ---------------------------------------------------------------- 录入 ----
    const form = document.querySelector("[data-fitness-form]");
    if (!form) return;

    const stack = form.querySelector("[data-exercise-stack]");
    const addRow = form.querySelector("[data-add-row]");
    const status = form.querySelector("[data-fitness-status]");
    const submit = form.querySelector("[data-fitness-submit]");
    const saveState = form.querySelector("[data-save-state]");
    const rpeHint = form.querySelector("[data-rpe-hint]");
    const weightSteps = (form.dataset.weights || "").split(",").filter(Boolean);

    function say(message, tone) {
        status.textContent = message || "";
        status.classList.toggle("is-error", tone === "error");
        status.classList.toggle("is-ok", tone === "ok");
    }

    function markDirty() {
        if (saveState) saveState.textContent = "未保存";
    }

    // 点击类的改动（加减组、勾完成、切类型/RPE）也要落进草稿。
    form.addEventListener("click", function (event) {
        if (event.target.closest("button")) scheduleDraft();
    });

    function activeValue(group) {
        const button = group && group.querySelector("button.is-active");
        return button ? button.dataset.value : null;
    }

    function pressGroup(group, button) {
        group.querySelectorAll("button").forEach(function (other) {
            other.classList.toggle("is-active", other === button);
            other.setAttribute("aria-pressed", String(other === button));
        });
    }

    // 一个动作的小计，改一个数字就重算，不用等保存。
    function refresh(card) {
        const kind = card.dataset.kind;
        const rows = card.querySelectorAll("[data-set]");
        let volume = 0, complete = true, left = 0, right = 0, seconds = 0;

        rows.forEach(function (row, index) {
            const indexCell = row.querySelector(".fit-set-index");
            if (indexCell) indexCell.textContent = String(index + 1);
            const field = function (name) {
                const input = row.querySelector('[data-field="' + name + '"]');
                return input ? number(input.value) : null;
            };
            if (kind === "static") {
                seconds += field("seconds") || 0;
                return;
            }
            const weight = field("weight");
            const l = field("left");
            const r = kind === "unilateral" ? field("right") : null;
            left += l || 0;
            right += r || 0;
            if (weight == null || (kind === "unilateral" ? (l == null && r == null) : l == null)) {
                complete = false;
                return;
            }
            volume += kind === "unilateral" ? weight * ((l || 0) + (r || 0)) : weight * l;
        });

        const summary = card.querySelector(".fit-exercise-sides");
        if (summary) {
            if (kind === "static") {
                summary.textContent = seconds + " 秒";
            } else if (kind === "unilateral") {
                const total = left + right;
                summary.textContent = "左 " + left + " · 右 " + right;
                summary.classList.toggle("is-off", total > 0 && Math.abs(left - right) * 200 / total >= 8);
            } else {
                summary.textContent = left + " 次";
            }
        }
        const volumeCell = card.querySelector("[data-exercise-volume]");
        if (volumeCell) volumeCell.textContent = (kind === "static" || !complete) ? "—" : format(volume) + " kg";
    }

    function renumber() {
        stack.querySelectorAll(".fit-exercise").forEach(function (card, index) {
            const badge = card.querySelector(".fit-exercise-index");
            if (badge) badge.textContent = index < 9 ? "0" + (index + 1) : String(index + 1);
        });
    }

    function fieldHTML(kind, values) {
        values = values || {};
        const box = function (name, placeholder, value, mode, list) {
            return '<label class="fit-field"><input data-field="' + name + '" placeholder="' + placeholder
                + '" inputmode="' + mode + '" value="' + (value == null ? "" : value) + '"'
                + (list ? ' list="fit-weight-steps"' : "") + ' aria-label="' + placeholder + '"></label>';
        };
        if (kind === "static") return box("seconds", "秒", values.seconds, "numeric");
        const weight = box("weight", "kg", values.weight, "decimal", true);
        if (kind === "unilateral") {
            return weight + box("left", "左", values.left, "numeric") + box("right", "右", values.right, "numeric");
        }
        return weight + box("left", "次", values.left, "numeric");
    }

    function headHTML(kind) {
        if (kind === "static") return "<span>组</span><span>时长<i>秒</i></span><span></span>";
        if (kind === "unilateral") {
            return "<span>组</span><span>重量<i>kg</i></span>"
                + '<span class="is-side">左<i>次</i></span><span class="is-side">右<i>次</i></span><span></span>';
        }
        return "<span>组</span><span>重量<i>kg</i></span><span>次数</span><span></span>";
    }

    function setHTML(kind, values, done) {
        values = values || {};
        const note = values.note || "";
        return '<div class="fit-set' + (done ? " is-done" : "") + (note ? " has-note" : "") + '" data-set>'
            + '<span class="fit-set-index"></span>' + fieldHTML(kind, values)
            + '<button class="fit-set-check" type="button" data-set-check aria-pressed="'
            + (done ? "true" : "false") + '" aria-label="标记完成">' + CHECK_SVG + "</button>"
            + REMOVE_BTN + noteInput(note) + "</div>";
    }

    function addExercise(name, sets) {
        const kind = KINDS[name] || "bilateral";
        const card = document.createElement("article");
        card.className = "fit-exercise"
            + (kind === "unilateral" ? " is-unilateral" : kind === "static" ? " is-static" : "");
        card.dataset.exercise = name;
        card.dataset.kind = kind;
        const rows = (sets && sets.length ? sets : [{}])
            .map(function (values) { return setHTML(kind, values, !!(values && values.done)); }).join("");
        card.innerHTML =
            '<div class="fit-exercise-head"><span class="fit-exercise-index"></span><h3>' + name + "</h3>"
            + '<span class="fit-exercise-sides"></span>'
            + '<span class="fit-exercise-volume" data-exercise-volume>—</span>'
            + '<button class="fit-icon-button" type="button" data-remove-exercise aria-label="删除' + name + '">'
            + TRASH_SVG + "</button></div>"
            + '<div class="fit-sets" data-sets><div class="fit-set-head" aria-hidden="true">' + headHTML(kind)
            + "</div>" + rows
            + '<button class="fit-ghost-button" type="button" data-add-set>+ 再加一组</button></div>';
        stack.appendChild(card);
        const chip = addRow.querySelector('[data-move="' + name + '"]');
        if (chip) chip.hidden = true;
        renumber();
        refresh(card);
        markDirty();
        return card;
    }

    // 点击代理：动作卡是动态的，逐个绑监听会漏掉后加的。
    form.addEventListener("click", function (event) {
        const check = event.target.closest("[data-set-check]");
        if (check) {
            const row = check.closest(".fit-set");
            const done = row.classList.toggle("is-done");
            check.setAttribute("aria-pressed", String(done));
            markDirty();
            return;
        }
        const addSet = event.target.closest("[data-add-set]");
        if (addSet) {
            const card = addSet.closest(".fit-exercise");
            const rows = card.querySelectorAll("[data-set]");
            const last = rows[rows.length - 1];
            const carry = {};
            if (last) {
                // 沿用上一组的重量：健身房里单手操作，能少敲一个数是一个。
                const weight = last.querySelector('[data-field="weight"]');
                if (weight) carry.weight = weight.value;
            }
            addSet.insertAdjacentHTML("beforebegin", setHTML(card.dataset.kind, carry, false));
            refresh(card);
            markDirty();
            const next = card.querySelectorAll("[data-set]");
            const input = next[next.length - 1].querySelector("input:not([data-field='weight'])");
            if (input) input.focus();
            return;
        }
        const dropSet = event.target.closest("[data-remove-set]");
        if (dropSet) {
            const card = dropSet.closest(".fit-exercise");
            const row = dropSet.closest(".fit-set");
            if (card.querySelectorAll("[data-set]").length === 1) {
                // 最后一组删掉就等于删动作，那有专门的按钮，别在这儿留个空壳。
                say("这是最后一组；要去掉整个动作请用右上角的删除。", "error");
                return;
            }
            row.remove();
            refresh(card);
            markDirty();
            return;
        }
        const remove = event.target.closest("[data-remove-exercise]");
        if (remove) {
            const card = remove.closest(".fit-exercise");
            const chip = addRow.querySelector('[data-move="' + card.dataset.exercise + '"]');
            if (chip) chip.hidden = false;
            card.remove();
            renumber();
            markDirty();
            return;
        }
        const chip = event.target.closest("[data-move]");
        if (chip && addRow.contains(chip)) {
            addExercise(chip.dataset.move).scrollIntoView({ block: "nearest" });
            return;
        }
        const dayType = event.target.closest("[data-day-type] button");
        if (dayType) {
            pressGroup(form.querySelector("[data-day-type]"), dayType);
            markDirty();
            return;
        }
        const rpe = event.target.closest("[data-rpe] button");
        if (rpe) {
            pressGroup(form.querySelector("[data-rpe]"), rpe);
            rpeHint.textContent = RPE_HINTS[rpe.dataset.value] || "";
            markDirty();
        }
    });

    // 备注框跟着内容长高，别让长备注藏在一行里。
    function growNote(note) {
        note.style.height = "auto";
        note.style.height = note.scrollHeight + "px";
    }

    form.addEventListener("input", function (event) {
        if (event.target.dataset.field === "note") {
            event.target.closest(".fit-set").classList.toggle("has-note", !!event.target.value.trim());
            growNote(event.target);
        }
        const card = event.target.closest(".fit-exercise");
        if (card) refresh(card);
        markDirty();
        scheduleDraft();
    });

    // 重量档位：手头的哑铃就这几档，给个候选省得把 6.5 打成 65。
    if (weightSteps.length) {
        const list = document.createElement("datalist");
        list.id = "fit-weight-steps";
        list.innerHTML = weightSteps.map(function (step) {
            return '<option value="' + step + '"></option>';
        }).join("");
        form.appendChild(list);
        form.querySelectorAll('[data-field="weight"]').forEach(function (input) {
            input.setAttribute("list", "fit-weight-steps");
        });
    }

    form.querySelectorAll('[data-field="note"]').forEach(function (note) {
        if (note.value.trim()) growNote(note);
    });
    form.addEventListener("focusin", function (event) {
        if (event.target.dataset.field === "note") growNote(event.target);
    });

    const initialRpe = activeValue(form.querySelector("[data-rpe]"));
    if (initialRpe) rpeHint.textContent = RPE_HINTS[initialRpe] || "";
    stack.querySelectorAll(".fit-exercise").forEach(refresh);

    const repeat = form.querySelector("[data-repeat-last]");
    if (repeat) {
        repeat.addEventListener("click", function () {
            const previous = window.__fitnessLastSession;
            if (!previous || !previous.length) {
                say("还没有可以套用的上一次训练。", "error");
                return;
            }
            stack.replaceChildren();
            addRow.querySelectorAll("[data-move]").forEach(function (chip) { chip.hidden = false; });
            previous.forEach(function (item) {
                addExercise(item.name, item.sets.map(function (entry) {
                    return { weight: entry.weight };  // 重量沿用，次数当场填
                }));
            });
            say("已套用上次的动作，次数还要你自己填。", "ok");
        });
    }

    function collect() {
        const exercises = [];
        stack.querySelectorAll(".fit-exercise").forEach(function (card) {
            const kind = card.dataset.kind;
            const sets = [];
            card.querySelectorAll("[data-set]").forEach(function (row) {
                const field = function (name) {
                    const input = row.querySelector('[data-field="' + name + '"]');
                    return input ? number(input.value) : null;
                };
                if (kind === "static") {
                    const seconds = field("seconds");
                    if (seconds != null) {
                        const staticNote = row.querySelector('[data-field="note"]');
                        sets.push({
                            seconds: seconds,
                            note: staticNote ? staticNote.value.trim() : "",
                            done: row.classList.contains("is-done"),
                        });
                    }
                    return;
                }
                const noteInput = row.querySelector('[data-field="note"]');
                const note = noteInput ? noteInput.value.trim() : "";
                const entry = { weight: field("weight"), left: field("left"), note: note };
                entry.right = kind === "unilateral" ? field("right") : null;
                if (entry.weight == null && entry.left == null && entry.right == null && !note) return;
                entry.done = row.classList.contains("is-done");   // 只给草稿用，服务端不读
                sets.push(entry);
            });
            if (sets.length) exercises.push({ name: card.dataset.exercise, sets: sets });
        });
        const value = function (selector) {
            const input = form.querySelector(selector);
            return input ? number(input.value) : null;
        };
        const note = form.querySelector('[data-field="note"]');
        return {
            entry_date: form.dataset.entryDate,
            day_type: activeValue(form.querySelector("[data-day-type]")),
            exercises: exercises,
            duration_min: value('[data-field="duration_min"]'),
            rpe: number(activeValue(form.querySelector("[data-rpe]"))),
            weight_kg: value('[data-field="weight_kg"]'),
            waist_cm: value('[data-field="waist_cm"]'),
            note: note ? note.value : "",
        };
    }

    // ---------------------------------------------------------------- 草稿 ----
    /* 一次训练的录入常常跨大半天：早上称体重，晚上才练完回来补组数。
       中间关掉页面不该把输入弄丢，所以每次改动都把整张表单写进 localStorage。

       恢复的策略分两种，因为风险不一样：
         服务端今天还没有记录 —— 直接恢复，没有什么可覆盖的；
         服务端已经有记录 —— 只提示，让人自己决定。草稿可能是另一台设备
         保存之前留下的残影，静默盖上去就等于偷偷回滚了一次保存。 */
    const DRAFT_KEY = "fitness-draft";
    let draftTimer = null;

    function readDraft() {
        try {
            const raw = localStorage.getItem(DRAFT_KEY);
            if (!raw) return null;
            const draft = JSON.parse(raw);
            // 隔天的草稿没有意义，当天才认。
            return draft && draft.entry_date === form.dataset.entryDate ? draft : null;
        } catch (error) {
            return null;
        }
    }

    function writeDraft() {
        try {
            const payload = collect();
            payload.saved_at = Date.now();
            localStorage.setItem(DRAFT_KEY, JSON.stringify(payload));
            if (saveState) saveState.textContent = "草稿已存 " + clock(payload.saved_at);
        } catch (error) {
            // 无痕模式、存储配额满——存不下就算了，不该拦着人继续录入。
        }
    }

    function dropDraft() {
        try { localStorage.removeItem(DRAFT_KEY); } catch (error) { /* 同上 */ }
    }

    function clock(stamp) {
        const when = new Date(stamp);
        return String(when.getHours()).padStart(2, "0") + ":"
            + String(when.getMinutes()).padStart(2, "0");
    }

    function scheduleDraft() {
        window.clearTimeout(draftTimer);
        draftTimer = window.setTimeout(writeDraft, 600);
    }

    function applyDraft(draft) {
        const dayGroup = form.querySelector("[data-day-type]");
        const dayButton = dayGroup && dayGroup.querySelector('[data-value="' + draft.day_type + '"]');
        if (dayButton) pressGroup(dayGroup, dayButton);

        stack.replaceChildren();
        addRow.querySelectorAll("[data-move]").forEach(function (chip) { chip.hidden = false; });
        (draft.exercises || []).forEach(function (item) { addExercise(item.name, item.sets); });

        const fill = function (selector, value) {
            const input = form.querySelector(selector);
            if (input) input.value = value == null ? "" : value;
        };
        fill('[data-field="duration_min"]', draft.duration_min);
        fill('[data-field="weight_kg"]', draft.weight_kg);
        fill('[data-field="waist_cm"]', draft.waist_cm);
        const note = form.querySelector('[data-field="note"]');
        if (note) note.value = draft.note || "";

        const rpeGroup = form.querySelector("[data-rpe]");
        const rpeButton = rpeGroup && draft.rpe
            && rpeGroup.querySelector('[data-value="' + draft.rpe + '"]');
        if (rpeButton) {
            pressGroup(rpeGroup, rpeButton);
            rpeHint.textContent = RPE_HINTS[draft.rpe] || "";
        }
        form.querySelectorAll('[data-field="note"]').forEach(function (field) {
            if (field.value.trim()) growNote(field);
        });
    }

    (function restoreDraft() {
        const draft = readDraft();
        if (!draft) return;
        const alreadySaved = form.dataset.saved === "1";
        if (!alreadySaved) {
            applyDraft(draft);
            say("已恢复 " + clock(draft.saved_at) + " 的草稿，还没存进去。");
            return;
        }
        // 服务端已有记录：给个选择，不擅自覆盖。
        const bar = document.createElement("div");
        bar.className = "fit-draft-bar";
        bar.innerHTML = '<span>有一份 ' + clock(draft.saved_at)
            + ' 的未保存草稿，和已存的记录不一定一致。</span>'
            + '<button type="button" data-draft-restore>恢复草稿</button>'
            + '<button type="button" data-draft-discard>丢弃</button>';
        form.insertBefore(bar, form.firstElementChild.nextSibling);
        bar.querySelector("[data-draft-restore]").addEventListener("click", function () {
            applyDraft(draft);
            bar.remove();
            say("已恢复草稿，确认无误后记得保存。");
        });
        bar.querySelector("[data-draft-discard]").addEventListener("click", function () {
            dropDraft();
            bar.remove();
            say("草稿已丢弃。");
        });
    })();

    // ------------------------------------------------------ 身体数据直存 ----
    /* 体重是早上称的，腰围是偶尔量的，训练是晚上练的。这些数字量出来就已经
       是定数，不是半成品，所以不走草稿：改一下就直接落进 body_metrics，
       不用先凑出一次完整的训练，换台设备打开也还在。 */
    (function bodyMetrics() {
        const inputs = form.querySelectorAll("[data-body-field]");
        if (!inputs.length) return;
        const LABELS = { weight_kg: ["体重", "kg"], waist_cm: ["腰围", "cm"] };

        inputs.forEach(function (input) {
            let lastSent = input.value.trim();
            input.addEventListener("change", async function () {
                const value = input.value.trim();
                if (value === lastSent) return;
                if (!value) { lastSent = value; return; }   // 留空就是没量，不是要清掉
                const field = input.dataset.bodyField;
                const label = LABELS[field] || [field, ""];
                const body = {};
                body[field] = number(value);
                try {
                    const response = await fetch("/fitness/body", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                            "X-CSRF-Token": window.BLOG_CSRF_TOKEN || "",
                        },
                        body: JSON.stringify(body),
                    });
                    const result = await response.json().catch(function () { return {}; });
                    if (!response.ok) throw new Error(result.message || label[0] + "没记上。");
                    lastSent = value;
                    say(label[0] + " " + value + " " + label[1] + " 已单独记下，不用等训练保存。", "ok");
                } catch (error) {
                    say(error.message, "error");
                }
            });
        });
    })();

    submit.addEventListener("click", async function () {
        const payload = collect();
        if (payload.day_type !== "休息" && !payload.exercises.length) {
            say("至少记一个动作，或者把类型改成休息。", "error");
            return;
        }
        submit.disabled = true;
        say("正在保存…");
        try {
            const response = await fetch(form.dataset.endpoint, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRF-Token": window.BLOG_CSRF_TOKEN || "",
                },
                body: JSON.stringify(payload),
            });
            const result = await response.json().catch(function () { return {}; });
            if (!response.ok) throw new Error(result.message || "保存失败，请再试一次。");
            const partial = result.totals && result.totals.partial;
            say((result.message || "已保存。")
                + (partial ? " 有组没填完，今天的容量算不出来。" : ""), partial ? "error" : "ok");
            if (saveState) saveState.textContent = "已保存";
            submit.textContent = "更新训练";
        } catch (error) {
            say(error.message, "error");
        } finally {
            submit.disabled = false;
        }
    });
})();
