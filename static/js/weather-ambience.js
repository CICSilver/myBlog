/* Ambient weather: asks the server what the sky is doing where the visitor is,
   then drifts rain or snow across the page. Purely decorative, so every step
   fails quietly and the page never waits on it. */
(function () {
    "use strict";

    const STORAGE_KEY = "silver-blog-weather";
    const CACHE_KEY = "silver-blog-weather-cache";
    const CACHE_TTL_MS = 10 * 60 * 1000;
    const PARTICLE_CATEGORIES = ["rain", "snow", "sleet"];

    // Particles per layer at intensity 1 / 2 / 3, for a 1280x800 viewport.
    const DENSITY = {
        rain: { back: [70, 130, 205], front: [7, 12, 18] },
        snow: { back: [34, 58, 96], front: [5, 9, 14] },
    };
    const MAX_PARTICLES = { back: 260, front: 26 };
    const REFERENCE_AREA = 1280 * 800;

    const root = document.documentElement;
    const container = document.querySelector("[data-weather-ambience]");
    const toggle = document.querySelector("[data-weather-toggle]");

    if (!container) {
        return;
    }

    const reducedMotionQuery = window.matchMedia
        ? window.matchMedia("(prefers-reduced-motion: reduce)")
        : null;

    const layers = Array.from(container.querySelectorAll("[data-weather-canvas]")).map((canvas) => ({
        name: canvas.dataset.weatherCanvas,
        canvas: canvas,
        context: canvas.getContext("2d"),
        width: 0,
        height: 0,
        particles: [],
    }));

    const state = {
        category: "",
        intensity: 0,
        enabled: readPreference(),
        colors: readColors(),
        frame: 0,
        lastFrameTime: 0,
    };

    function readPreference() {
        try {
            return window.localStorage.getItem(STORAGE_KEY) !== "off";
        } catch (error) {
            return true;
        }
    }

    function writePreference(enabled) {
        try {
            window.localStorage.setItem(STORAGE_KEY, enabled ? "on" : "off");
        } catch (error) {
            /* Private browsing: the choice simply lasts for this page. */
        }
    }

    function readColors() {
        const styles = window.getComputedStyle(root);
        return {
            rainBack: styles.getPropertyValue("--weather-rain").trim() || "rgba(96, 108, 126, 0.42)",
            rainFront: styles.getPropertyValue("--weather-rain-front").trim() || "rgba(96, 108, 126, 0.24)",
            snowBack: styles.getPropertyValue("--weather-snow").trim() || "rgba(146, 158, 178, 0.5)",
            snowFront: styles.getPropertyValue("--weather-snow-front").trim() || "rgba(146, 158, 178, 0.3)",
            snowEdge: styles.getPropertyValue("--weather-snow-edge").trim() || "transparent",
        };
    }

    function prefersReducedMotion() {
        return Boolean(reducedMotionQuery && reducedMotionQuery.matches);
    }

    function parseOverride() {
        const requested = new URLSearchParams(window.location.search).get("weather");
        if (!requested) {
            return null;
        }

        const parts = requested.split(":");
        if (parts[0] === "off") {
            return { available: false, category: "", intensity: 0 };
        }

        return {
            available: true,
            category: parts[0],
            intensity: Number(parts[1]) || 2,
            condition: "预览",
            temperature_c: "",
            city: "",
        };
    }

    function readCachedWeather() {
        try {
            const raw = window.sessionStorage.getItem(CACHE_KEY);
            if (!raw) {
                return null;
            }

            const cached = JSON.parse(raw);
            if (!cached || Date.now() - cached.storedAt > CACHE_TTL_MS) {
                return null;
            }

            return cached.payload;
        } catch (error) {
            return null;
        }
    }

    function writeCachedWeather(payload) {
        try {
            window.sessionStorage.setItem(
                CACHE_KEY,
                JSON.stringify({ storedAt: Date.now(), payload: payload })
            );
        } catch (error) {
            /* Nothing to do: the next page view just asks again. */
        }
    }

    function describe(payload) {
        if (!payload || !payload.available) {
            return "";
        }

        const parts = [payload.city, payload.condition];
        if (payload.temperature_c) {
            parts.push(payload.temperature_c + "°C");
        }

        return parts.filter(Boolean).join(" ");
    }

    function updateToggle(payload) {
        if (!toggle) {
            return;
        }

        const hasWeather = PARTICLE_CATEGORIES.indexOf(state.category) !== -1;
        toggle.hidden = !hasWeather;
        if (!hasWeather) {
            return;
        }

        const reading = describe(payload);
        const action = state.enabled ? "关闭天气动效" : "开启天气动效";
        const title = reading ? action + "（" + reading + "）" : action;

        toggle.setAttribute("aria-pressed", state.enabled ? "true" : "false");
        toggle.setAttribute("aria-label", title);
        toggle.setAttribute("title", title);

        const labelNode = toggle.querySelector("[data-weather-toggle-label]");
        if (labelNode) {
            labelNode.textContent = reading || "天气动效";
        }
    }

    function resizeLayers() {
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const width = window.innerWidth;
        const height = window.innerHeight;

        layers.forEach((layer) => {
            layer.width = width;
            layer.height = height;
            layer.canvas.width = Math.round(width * dpr);
            layer.canvas.height = Math.round(height * dpr);
            layer.context.setTransform(dpr, 0, 0, dpr, 0, 0);
        });
    }

    function particleCount(kind, layerName, intensity) {
        const table = DENSITY[kind];
        if (!table) {
            return 0;
        }

        const level = Math.min(Math.max(intensity, 1), 3);
        const base = table[layerName][level - 1];
        const area = Math.max(window.innerWidth * window.innerHeight, 1);
        const scaled = Math.round(base * Math.sqrt(area / REFERENCE_AREA));

        return Math.min(scaled, MAX_PARTICLES[layerName]);
    }

    function createRainDrop(layer, isFront, intensity) {
        const speedBase = isFront ? 1500 : 760;
        return {
            kind: "rain",
            x: Math.random() * (layer.width + 220) - 160,
            y: Math.random() * layer.height,
            length: isFront ? 34 + Math.random() * 32 : 11 + Math.random() * 15,
            speed: speedBase + Math.random() * 340 + intensity * 90,
            width: isFront ? 1.6 + Math.random() * 0.9 : 0.8 + Math.random() * 0.6,
        };
    }

    function createSnowFlake(layer, isFront) {
        return {
            kind: "snow",
            x: Math.random() * (layer.width + 80) - 40,
            y: Math.random() * layer.height,
            radius: isFront ? 2.8 + Math.random() * 2.2 : 1 + Math.random() * 1.6,
            speed: (isFront ? 46 : 22) + Math.random() * 34,
            sway: 8 + Math.random() * 20,
            phase: Math.random() * Math.PI * 2,
            spin: 0.5 + Math.random() * 0.8,
        };
    }

    function fillLayer(layer) {
        const isFront = layer.name === "front";
        const particles = [];

        if (state.category === "rain" || state.category === "sleet") {
            const share = state.category === "sleet" ? 0.55 : 1;
            const total = Math.round(particleCount("rain", layer.name, state.intensity) * share);
            for (let index = 0; index < total; index += 1) {
                particles.push(createRainDrop(layer, isFront, state.intensity));
            }
        }

        if (state.category === "snow" || state.category === "sleet") {
            const share = state.category === "sleet" ? 0.55 : 1;
            const total = Math.round(particleCount("snow", layer.name, state.intensity) * share);
            for (let index = 0; index < total; index += 1) {
                particles.push(createSnowFlake(layer, isFront));
            }
        }

        layer.particles = particles;
        layer.canvas.classList.toggle("is-visible", particles.length > 0);
    }

    function windRatio() {
        return 0.16 + state.intensity * 0.02;
    }

    function drawLayer(layer, deltaSeconds) {
        const context = layer.context;
        const isFront = layer.name === "front";
        const wind = windRatio();

        context.clearRect(0, 0, layer.width, layer.height);

        const drawsSnowEdge = !isFront && state.colors.snowEdge !== "transparent";

        context.strokeStyle = isFront ? state.colors.rainFront : state.colors.rainBack;
        context.fillStyle = isFront ? state.colors.snowFront : state.colors.snowBack;
        context.lineCap = "round";

        layer.particles.forEach((particle) => {
            if (particle.kind === "rain") {
                particle.y += particle.speed * deltaSeconds;
                particle.x += particle.speed * wind * deltaSeconds;

                if (particle.y - particle.length > layer.height) {
                    particle.y = -particle.length - Math.random() * 120;
                    particle.x = Math.random() * (layer.width + 220) - 160;
                }

                context.strokeStyle = isFront ? state.colors.rainFront : state.colors.rainBack;
                context.lineWidth = particle.width;
                context.beginPath();
                context.moveTo(particle.x, particle.y);
                context.lineTo(particle.x - particle.length * wind, particle.y - particle.length);
                context.stroke();
                return;
            }

            particle.phase += particle.spin * deltaSeconds;
            particle.y += particle.speed * deltaSeconds;
            particle.x += Math.sin(particle.phase) * particle.sway * deltaSeconds;

            if (particle.y - particle.radius > layer.height) {
                particle.y = -particle.radius - Math.random() * 80;
                particle.x = Math.random() * (layer.width + 80) - 40;
            }

            context.beginPath();
            context.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2);
            context.fill();

            // On light paper a plain white dot disappears; a hairline edge
            // keeps it reading as a flake. The blurred near layer skips it.
            if (drawsSnowEdge) {
                context.strokeStyle = state.colors.snowEdge;
                context.lineWidth = 0.7;
                context.stroke();
            }
        });
    }

    function step(timestamp) {
        state.frame = 0;

        if (!state.lastFrameTime) {
            state.lastFrameTime = timestamp;
        }

        // Clamp the step so a backgrounded tab does not teleport every drop.
        const deltaSeconds = Math.min((timestamp - state.lastFrameTime) / 1000, 0.05);
        state.lastFrameTime = timestamp;

        layers.forEach((layer) => drawLayer(layer, deltaSeconds));
        schedule();
    }

    function schedule() {
        if (state.frame) {
            return;
        }

        state.frame = window.requestAnimationFrame(step);
    }

    function stop() {
        if (state.frame) {
            window.cancelAnimationFrame(state.frame);
            state.frame = 0;
        }

        state.lastFrameTime = 0;
        layers.forEach((layer) => {
            layer.particles = [];
            layer.canvas.classList.remove("is-visible");
            layer.context.clearRect(0, 0, layer.width, layer.height);
        });
    }

    function render() {
        const shouldAnimate =
            state.enabled &&
            !prefersReducedMotion() &&
            PARTICLE_CATEGORIES.indexOf(state.category) !== -1;

        if (!shouldAnimate) {
            stop();
            return;
        }

        resizeLayers();
        layers.forEach(fillLayer);

        if (!document.hidden) {
            schedule();
        }
    }

    function applyWeather(payload) {
        const available = Boolean(payload && payload.available && payload.category);
        state.category = available ? payload.category : "";
        state.intensity = available ? Number(payload.intensity) || 0 : 0;

        if (state.category) {
            root.dataset.weather = state.category;
        } else {
            delete root.dataset.weather;
        }

        updateToggle(payload);
        render();
    }

    function requestWeather() {
        const override = parseOverride();
        if (override) {
            applyWeather(override);
            return;
        }

        const cached = readCachedWeather();
        if (cached) {
            applyWeather(cached);
            return;
        }

        const endpoint = container.dataset.weatherEndpoint;
        if (!endpoint || !window.fetch) {
            return;
        }

        window
            .fetch(endpoint, { headers: { Accept: "application/json" }, credentials: "same-origin" })
            .then((response) => (response.ok ? response.json() : null))
            .then((payload) => {
                if (!payload) {
                    return;
                }

                writeCachedWeather(payload);
                applyWeather(payload);
            })
            .catch(() => {
                /* No weather, no ambience: the page is complete without it. */
            });
    }

    function watchTheme() {
        const observer = new MutationObserver(() => {
            state.colors = readColors();
        });

        observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    }

    function bindEvents() {
        let resizeTimer = 0;
        window.addEventListener("resize", () => {
            window.clearTimeout(resizeTimer);
            resizeTimer = window.setTimeout(render, 220);
        });

        document.addEventListener("visibilitychange", () => {
            if (document.hidden) {
                if (state.frame) {
                    window.cancelAnimationFrame(state.frame);
                    state.frame = 0;
                }
                state.lastFrameTime = 0;
                return;
            }

            render();
        });

        if (reducedMotionQuery && typeof reducedMotionQuery.addEventListener === "function") {
            reducedMotionQuery.addEventListener("change", render);
        }

        if (toggle) {
            // Keep the click from pulling focus off whatever the reader was doing.
            toggle.addEventListener("mousedown", (event) => event.preventDefault());
            toggle.addEventListener("click", () => {
                state.enabled = !state.enabled;
                writePreference(state.enabled);
                updateToggle(parseOverride() || readCachedWeather());
                render();
            });
        }
    }

    watchTheme();
    bindEvents();
    requestWeather();
})();
