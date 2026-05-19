(function () {
    const config = window.BLOG_ARTICLE_VIEW_TRACKING;
    if (!config || !config.endpoint) {
        return;
    }

    const minimumSeconds = Number(config.minimum_seconds) || 15;
    const heartbeatSeconds = Number(config.heartbeat_seconds) || 15;
    const maxReadingSeconds = 30 * 60;
    const viewSessionId = createViewSessionId();
    let activeMilliseconds = 0;
    let lastTick = Date.now();
    let lastReportedSeconds = 0;
    let reportInFlight = false;

    function createViewSessionId() {
        if (window.crypto && typeof window.crypto.randomUUID === 'function') {
            return window.crypto.randomUUID();
        }

        const randomPart = Math.random().toString(36).slice(2);
        return `${Date.now().toString(36)}-${randomPart}`;
    }

    function pageIsVisible() {
        return document.visibilityState === 'visible';
    }

    function tick() {
        const now = Date.now();
        if (pageIsVisible()) {
            activeMilliseconds += now - lastTick;
            activeMilliseconds = Math.min(activeMilliseconds, maxReadingSeconds * 1000);
        }
        lastTick = now;
    }

    function activeSeconds() {
        tick();
        return Math.floor(activeMilliseconds / 1000);
    }

    function shouldReport(seconds, force) {
        if (seconds < minimumSeconds) {
            return false;
        }

        if (force) {
            return seconds > lastReportedSeconds;
        }

        return seconds - lastReportedSeconds >= heartbeatSeconds;
    }

    function report(force) {
        const seconds = activeSeconds();
        if (!shouldReport(seconds, force) || reportInFlight) {
            return;
        }

        lastReportedSeconds = seconds;
        reportInFlight = true;

        fetch(config.endpoint, {
            method: 'POST',
            credentials: 'same-origin',
            keepalive: true,
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': window.BLOG_CSRF_TOKEN || '',
            },
            body: JSON.stringify({
                year: config.year,
                month: config.month,
                html_title: config.html_title,
                view_session_id: viewSessionId,
                reading_seconds: seconds,
            }),
        }).catch(function () {
            lastReportedSeconds = Math.max(0, lastReportedSeconds - heartbeatSeconds);
        }).finally(function () {
            reportInFlight = false;
        });
    }

    window.setInterval(function () {
        report(false);
    }, 1000);

    document.addEventListener('visibilitychange', function () {
        tick();
        if (!pageIsVisible()) {
            report(true);
        }
    });

    window.addEventListener('pagehide', function () {
        report(true);
    });
})();
