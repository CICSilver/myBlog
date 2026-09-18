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
        return '<div class="fit-set' + (done ? " is-done" : "") + '" data-set>'
            + '<span class="fit-set-index"></span>' + fieldHTML(kind, values)
            + '<button class="fit-set-check" type="button" data-set-check aria-pressed="'
            + (done ? "true" : "false") + '" aria-label="标记完成">' + CHECK_SVG + "</button></div>";
    }

    function addExercise(name, sets) {
        const kind = KINDS[name] || "bilateral";
        const card = document.createElement("article");
        card.className = "fit-exercise"
            + (kind === "unilateral" ? " is-unilateral" : kind === "static" ? " is-static" : "");
        card.dataset.exercise = name;
        card.dataset.kind = kind;
        const rows = (sets && sets.length ? sets : [{}])
            .map(function (values) { return setHTML(kind, values, false); }).join("");
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

    form.addEventListener("input", function (event) {
        const card = event.target.closest(".fit-exercise");
        if (card) refresh(card);
        markDirty();
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
                    if (field("seconds") != null) sets.push({ seconds: field("seconds") });
                    return;
                }
                const entry = { weight: field("weight"), left: field("left") };
                entry.right = kind === "unilateral" ? field("right") : null;
                if (entry.weight == null && entry.left == null && entry.right == null) return;
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
            note: note ? note.value : "",
        };
    }

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
            say(result.message || "已保存。", "ok");
            if (saveState) saveState.textContent = "已保存";
            submit.textContent = "更新训练";
        } catch (error) {
            say(error.message, "error");
        } finally {
            submit.disabled = false;
        }
    });
})();
