(function () {
    "use strict";

    const SVG_NS = "http://www.w3.org/2000/svg";
    const DAY_MS = 86400000;
    const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    /* ---------- 今夕：月相、农历、节气与物候 ---------- */

    const SYNODIC_MONTH = 29.530588853;
    const REFERENCE_NEW_MOON = Date.UTC(2000, 0, 6, 18, 14);
    const WEEKDAYS = "日一二三四五六";
    const LUNAR_DAYS = [
        "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
        "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
        "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十",
    ];
    const PENTAD_NAMES = ["初候", "二候", "三候"];

    // 自小寒起的二十四节气，C 值为 21 世纪通用公式常数，PENTADS 为对应的七十二候。
    const TERMS = [
        "小寒", "大寒", "立春", "雨水", "惊蛰", "春分", "清明", "谷雨", "立夏", "小满", "芒种", "夏至",
        "小暑", "大暑", "立秋", "处暑", "白露", "秋分", "寒露", "霜降", "立冬", "小雪", "大雪", "冬至",
    ];
    const TERM_C = [
        5.4055, 20.12, 3.87, 18.73, 5.63, 20.646, 4.81, 20.1, 5.52, 21.04, 5.678, 21.37,
        7.108, 22.83, 7.5, 23.13, 7.646, 23.042, 8.318, 23.438, 7.438, 22.36, 7.18, 21.94,
    ];
    const TERM_CORRECTIONS = {
        "2019-0": -1, "2082-1": 1, "2026-3": -1, "2084-5": 1, "2008-9": 1,
        "2016-12": 1, "2002-14": 1, "2089-19": 1, "2089-20": 1, "2021-23": -1,
    };
    const PENTADS = [
        ["雁北乡", "鹊始巢", "雉始雊"], ["鸡始乳", "征鸟厉疾", "水泽腹坚"],
        ["东风解冻", "蛰虫始振", "鱼陟负冰"], ["獭祭鱼", "鸿雁来", "草木萌动"],
        ["桃始华", "仓庚鸣", "鹰化为鸠"], ["玄鸟至", "雷乃发声", "始电"],
        ["桐始华", "田鼠化为鴽", "虹始见"], ["萍始生", "鸣鸠拂其羽", "戴胜降于桑"],
        ["蝼蝈鸣", "蚯蚓出", "王瓜生"], ["苦菜秀", "靡草死", "麦秋至"],
        ["螳螂生", "鵙始鸣", "反舌无声"], ["鹿角解", "蜩始鸣", "半夏生"],
        ["温风至", "蟋蟀居宇", "鹰始挚"], ["腐草为萤", "土润溽暑", "大雨时行"],
        ["凉风至", "白露降", "寒蝉鸣"], ["鹰乃祭鸟", "天地始肃", "禾乃登"],
        ["鸿雁来", "玄鸟归", "群鸟养羞"], ["雷始收声", "蛰虫坯户", "水始涸"],
        ["鸿雁来宾", "雀入大水为蛤", "菊有黄华"], ["豺乃祭兽", "草木黄落", "蛰虫咸俯"],
        ["水始冰", "地始冻", "雉入大水为蜃"], ["虹藏不见", "天气上升", "闭塞而成冬"],
        ["鹖鴠不鸣", "虎始交", "荔挺出"], ["蚯蚓结", "麋角解", "水泉动"],
    ];

    function startOfDay(date) {
        return new Date(date.getFullYear(), date.getMonth(), date.getDate());
    }

    function solarTermDate(year, index) {
        const y = year % 100;
        const leapBase = index < 4 ? y - 1 : y;
        let day = Math.floor(y * 0.2422 + TERM_C[index]) - Math.floor(leapBase / 4);
        day += TERM_CORRECTIONS[year + "-" + index] || 0;
        return new Date(year, Math.floor(index / 2), day);
    }

    function currentSolarTerm(date) {
        const today = startOfDay(date);
        const candidates = [{ index: 23, date: solarTermDate(today.getFullYear() - 1, 23) }];
        for (let index = 0; index < TERMS.length; index += 1) {
            candidates.push({ index, date: solarTermDate(today.getFullYear(), index) });
        }
        let current = candidates[0];
        candidates.forEach((candidate) => {
            if (candidate.date <= today) {
                current = candidate;
            }
        });
        const days = Math.round((today - current.date) / DAY_MS);
        const pentad = Math.min(2, Math.floor(days / 5));
        return {
            name: TERMS[current.index],
            days,
            pentadName: PENTAD_NAMES[pentad],
            pentad: PENTADS[current.index][pentad],
        };
    }

    function lunarLabel(date) {
        try {
            const parts = new Intl.DateTimeFormat("zh-CN-u-ca-chinese", {
                year: "numeric",
                month: "long",
                day: "numeric",
            }).formatToParts(date);
            const pick = (type) => (parts.find((part) => part.type === type) || {}).value || "";
            const yearName = pick("yearName");
            const month = pick("month");
            let day = pick("day");
            if (/^\d+$/.test(day)) {
                day = LUNAR_DAYS[Number(day) - 1] || day;
            }
            if (!month || !day) {
                return "";
            }
            return (yearName ? yearName + "年 " : "") + month + day;
        } catch (error) {
            return "";
        }
    }

    function moonPhase(date) {
        const age = ((((date.getTime() - REFERENCE_NEW_MOON) / DAY_MS) % SYNODIC_MONTH) + SYNODIC_MONTH) % SYNODIC_MONTH;
        const fraction = age / SYNODIC_MONTH;
        const illumination = (1 - Math.cos(2 * Math.PI * fraction)) / 2;
        let name;
        if (fraction < 0.034 || fraction > 0.966) {
            name = "朔";
        } else if (fraction < 0.216) {
            name = "蛾眉月";
        } else if (fraction < 0.284) {
            name = "上弦月";
        } else if (fraction < 0.466) {
            name = "盈凸月";
        } else if (fraction < 0.534) {
            name = "望月";
        } else if (fraction < 0.716) {
            name = "亏凸月";
        } else if (fraction < 0.784) {
            name = "下弦月";
        } else {
            name = "残月";
        }
        return { fraction, illumination, name };
    }

    // 以圆心为原点、半径 r 画出受光部分：一侧是半圆边缘，另一侧是晨昏线（椭圆弧）。
    function moonLitPath(fraction, r) {
        const waxing = fraction < 0.5;
        const terminator = Math.abs(Math.cos(2 * Math.PI * fraction)) * r;
        const crescent = fraction < 0.25 || fraction > 0.75;
        const limb = waxing
            ? "M0," + -r + " A" + r + "," + r + " 0 0 1 0," + r
            : "M0," + -r + " A" + r + "," + r + " 0 0 0 0," + r;
        const sweep = waxing ? (crescent ? 0 : 1) : (crescent ? 1 : 0);
        return limb + " A" + terminator.toFixed(2) + "," + r + " 0 0 " + sweep + " 0," + -r + " Z";
    }

    function initSky() {
        const sky = document.querySelector("[data-sky]");
        if (!sky) {
            return;
        }

        const now = new Date();
        const set = (selector, text) => {
            const node = sky.querySelector(selector);
            if (node && text) {
                node.textContent = text;
            }
        };

        const phase = moonPhase(now);
        const lit = sky.querySelector("[data-moon-lit]");
        if (lit) {
            lit.setAttribute("d", phase.illumination < 0.01 ? "" : moonLitPath(phase.fraction, 44));
        }

        const term = currentSolarTerm(now);
        const month = String(now.getMonth() + 1).padStart(2, "0");
        const day = String(now.getDate()).padStart(2, "0");
        set("[data-sky-date]", now.getFullYear() + "." + month + "." + day + " · 周" + WEEKDAYS[now.getDay()]);
        set("[data-sky-lunar]", lunarLabel(now));
        set("[data-sky-term]", term.days === 0 ? "今日" + term.name : term.name + " · " + term.pentadName);
        set("[data-sky-phase]", phase.name + " · " + Math.round(phase.illumination * 100) + "%");

        const pentad = sky.querySelector("[data-sky-pentad]");
        if (pentad) {
            const label = document.createElement("small");
            label.textContent = "物候";
            pentad.replaceChildren(label, document.createTextNode(term.pentad));
        }
    }

    /* ---------- 小径：穿过每篇文章的鸿爪 ---------- */

    function offsetWithin(element, root) {
        let x = 0;
        let y = 0;
        let node = element;
        while (node && node !== root) {
            x += node.offsetLeft;
            y += node.offsetTop;
            node = node.offsetParent;
        }
        return { x: x + element.offsetWidth / 2, y: y + element.offsetHeight / 2 };
    }

    function initTrail() {
        const root = document.querySelector("[data-trail-root]");
        const svg = root && root.querySelector("[data-trail]");
        if (!root || !svg) {
            return;
        }

        const groove = svg.querySelector(".trail-groove");
        const line = svg.querySelector(".trail-line");
        const printLayer = svg.querySelector(".trail-prints");
        const STEP = 36;
        let prints = [];
        let samples = [];
        let total = 0;
        let shown = 0;
        let frame = 0;

        function anchors() {
            return Array.from(root.querySelectorAll("[data-trail-start], [data-trail-node], [data-trail-end]"))
                .filter((element) => element.offsetParent !== null)
                .map((element) => offsetWithin(element, root));
        }

        function buildPath(points) {
            let d = "M" + points[0].x.toFixed(1) + "," + points[0].y.toFixed(1);
            for (let i = 1; i < points.length; i += 1) {
                const a = points[i - 1];
                const b = points[i];
                const bend = (b.y - a.y) * 0.5;
                d += " C" + a.x.toFixed(1) + "," + (a.y + bend).toFixed(1)
                    + " " + b.x.toFixed(1) + "," + (b.y - bend).toFixed(1)
                    + " " + b.x.toFixed(1) + "," + b.y.toFixed(1);
            }
            return d;
        }

        function lengthAtY(y) {
            if (!samples.length || y <= samples[0].y) {
                return 0;
            }
            let low = 0;
            let high = samples.length - 1;
            if (y >= samples[high].y) {
                return total;
            }
            while (high - low > 1) {
                const mid = (low + high) >> 1;
                if (samples[mid].y < y) {
                    low = mid;
                } else {
                    high = mid;
                }
            }
            return samples[low].length;
        }

        function update() {
            frame = 0;
            const rootTop = root.getBoundingClientRect().top;
            const reach = reduceMotion ? total : lengthAtY(window.innerHeight * 0.78 - rootTop);
            line.style.strokeDashoffset = String(total - reach);

            let next = shown;
            while (next < prints.length && prints[next].length <= reach) {
                prints[next].element.classList.add("is-down");
                next += 1;
            }
            while (next > 0 && prints[next - 1].length > reach) {
                next -= 1;
                prints[next].element.classList.remove("is-down");
            }
            shown = next;
        }

        function requestUpdate() {
            if (!frame) {
                frame = window.requestAnimationFrame(update);
            }
        }

        function layout() {
            const points = anchors();
            if (points.length < 2) {
                svg.hidden = true;
                return;
            }
            svg.hidden = false;

            const width = root.offsetWidth;
            const height = root.offsetHeight;
            svg.setAttribute("viewBox", "0 0 " + width + " " + height);
            svg.setAttribute("width", width);
            svg.setAttribute("height", height);

            const d = buildPath(points);
            groove.setAttribute("d", d);
            line.setAttribute("d", d);
            total = line.getTotalLength();
            line.style.strokeDasharray = total + " " + total;

            samples = [];
            for (let length = 0; length <= total; length += 6) {
                samples.push({ length, y: line.getPointAtLength(length).y });
            }

            const fragment = document.createDocumentFragment();
            prints = [];
            shown = 0;
            let side = 1;
            for (let length = STEP; length < total - STEP / 2; length += STEP) {
                const point = line.getPointAtLength(length);
                const ahead = line.getPointAtLength(Math.min(total, length + 2));
                const dx = ahead.x - point.x;
                const dy = ahead.y - point.y;
                const norm = Math.hypot(dx, dy) || 1;
                const offset = 6.5 * side;
                // 左右脚各自外撇一点，看起来才像在走路，而不是一列箭头。
                const angle = Math.atan2(dy, dx) * 180 / Math.PI - 90 + side * 12;
                const x = point.x - (dy / norm) * offset;
                const y = point.y + (dx / norm) * offset;
                const use = document.createElementNS(SVG_NS, "use");
                use.setAttribute("href", "#trail-claw");
                use.setAttribute("transform", "translate(" + x.toFixed(1) + " " + y.toFixed(1) + ") rotate(" + angle.toFixed(1) + ")");
                fragment.appendChild(use);
                prints.push({ element: use, length });
                side = -side;
            }
            printLayer.replaceChildren(fragment);
            update();
        }

        let layoutFrame = 0;
        function requestLayout() {
            if (!layoutFrame) {
                layoutFrame = window.requestAnimationFrame(() => {
                    layoutFrame = 0;
                    layout();
                });
            }
        }

        layout();
        window.addEventListener("scroll", requestUpdate, { passive: true });
        window.addEventListener("resize", requestLayout);
        window.addEventListener("load", requestLayout);
        if (document.fonts && document.fonts.ready) {
            document.fonts.ready.then(requestLayout);
        }
        if ("ResizeObserver" in window) {
            new ResizeObserver(requestLayout).observe(root);
        }
    }

    /* ---------- 入场 ---------- */

    function initReveal() {
        const items = document.querySelectorAll(".reveal");
        if (!items.length || reduceMotion || !("IntersectionObserver" in window)) {
            return;
        }

        const observer = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    entry.target.classList.add("is-inview");
                    observer.unobserve(entry.target);
                }
            });
        }, { rootMargin: "0px 0px -8% 0px" });

        items.forEach((item) => observer.observe(item));
        document.documentElement.classList.add("reveal-ready");
    }

    function init() {
        initSky();
        initReveal();
        initTrail();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
