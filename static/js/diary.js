(function () {
    function refreshDiarySummaries() {
        document.querySelectorAll("[data-diary-summary]").forEach(function (outer) {
            const inner = outer.querySelector("[data-diary-summary-inner]");
            const readMore = outer.closest(".diary-entry").querySelector("[data-diary-read-more]");

            readMore.hidden = true;
            if (inner.scrollHeight > outer.clientHeight) {
                readMore.hidden = false;
            }
        });
    }

    refreshDiarySummaries();
    window.addEventListener("resize", refreshDiarySummaries);

    const form = document.getElementById("diary-form");

    if (!form) {
        return;
    }

    const textarea = document.getElementById("diary-content");
    const imageInput = document.getElementById("diary-image-input");
    const imageSelect = document.getElementById("diary-image-select");
    const imageRemove = document.getElementById("diary-image-remove");
    const imagePreview = document.getElementById("diary-image-preview");
    const imagePreviewPanel = document.getElementById("diary-image-preview-panel");
    const imageName = document.getElementById("diary-image-name");
    const removeImage = document.getElementById("diary-remove-image");
    const latitude = document.getElementById("diary-latitude");
    const longitude = document.getElementById("diary-longitude");
    const accuracy = document.getElementById("diary-accuracy");
    const status = document.getElementById("diary-status");
    const submitButton = document.getElementById("diary-submit");
    const supportsBeforeInput = window.InputEvent && "inputType" in InputEvent.prototype;
    let previewObjectUrl = "";
    let isComposing = false;

    const SAVE_STATUS_KEY = "diarySaveStatus";

    function setStatus(message, tone) {
        status.textContent = message;
        status.dataset.tone = tone || "";
    }

    function rememberStatus(message, tone) {
        try {
            window.sessionStorage.setItem(SAVE_STATUS_KEY, JSON.stringify({ message: message, tone: tone }));
        } catch (error) {
            // sessionStorage 不可用时忽略，刷新后只是看不到提示。
        }
    }

    function restoreStatus() {
        let saved = null;
        try {
            saved = window.sessionStorage.getItem(SAVE_STATUS_KEY);
            window.sessionStorage.removeItem(SAVE_STATUS_KEY);
        } catch (error) {
            return;
        }

        if (!saved) {
            return;
        }

        try {
            const parsed = JSON.parse(saved);
            setStatus(parsed.message || "", parsed.tone || "");
        } catch (error) {
            // 忽略损坏的记录。
        }
    }

    restoreStatus();

    function describeGeolocationError(error) {
        const reasons = {
            1: "权限被拒绝",
            2: "位置不可用",
            3: "定位超时",
        };
        const code = error && typeof error.code === "number" ? error.code : 0;
        const reason = reasons[code] || "未知错误";
        const detail = error && error.message ? error.message : "";

        return "定位失败原因：" + reason + "（code " + code + (detail ? "，" + detail : "") + "）";
    }

    function insertChineseParagraphBreak() {
        const selectionStart = textarea.selectionStart;
        const selectionEnd = textarea.selectionEnd;
        const lineStart = textarea.value.lastIndexOf("\n", selectionStart - 1) + 1;
        const lineBeforeCaret = textarea.value.slice(lineStart, selectionStart);
        let replacementStart = selectionStart;
        let replacement = "\n　　";

        if (selectionStart === selectionEnd && lineBeforeCaret === "　　") {
            replacementStart = lineStart;
            replacement = "\n　　";
        }

        textarea.setRangeText(replacement, replacementStart, selectionEnd, "end");
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
    }

    textarea.addEventListener("compositionstart", function () {
        isComposing = true;
    });

    textarea.addEventListener("compositionend", function () {
        isComposing = false;
    });

    textarea.addEventListener("beforeinput", function (event) {
        if (
            isComposing ||
            event.isComposing ||
            (event.inputType !== "insertLineBreak" && event.inputType !== "insertParagraph")
        ) {
            return;
        }

        event.preventDefault();
        insertChineseParagraphBreak();
    });

    textarea.addEventListener("keydown", function (event) {
        if (
            supportsBeforeInput ||
            isComposing ||
            event.isComposing ||
            event.keyCode === 229 ||
            event.key !== "Enter"
        ) {
            return;
        }

        event.preventDefault();
        insertChineseParagraphBreak();
    });

    imageSelect.addEventListener("click", function () {
        imageInput.click();
    });

    imageInput.addEventListener("change", function () {
        const file = imageInput.files[0];

        if (!file) {
            return;
        }

        if (previewObjectUrl) {
            URL.revokeObjectURL(previewObjectUrl);
        }

        previewObjectUrl = URL.createObjectURL(file);
        imagePreview.src = previewObjectUrl;
        imagePreviewPanel.hidden = false;
        imageRemove.hidden = false;
        imageName.textContent = file.name;
        removeImage.value = "0";
    });

    imageRemove.addEventListener("click", function () {
        if (previewObjectUrl) {
            URL.revokeObjectURL(previewObjectUrl);
            previewObjectUrl = "";
        }

        imageInput.value = "";
        imagePreview.removeAttribute("src");
        imagePreviewPanel.hidden = true;
        imageRemove.hidden = true;
        imageName.textContent = "";
        removeImage.value = "1";
    });

    form.addEventListener("submit", function (event) {
        event.preventDefault();

        if (submitButton.disabled) {
            return;
        }

        submitButton.disabled = true;
        setStatus("正在保存日记。", "pending");

        let locationNote = "";

        const sendForm = function () {
            fetch(form.action, {
                method: "POST",
                body: new FormData(form),
                headers: {
                    "Accept": "application/json",
                    "X-CSRF-Token": window.BLOG_CSRF_TOKEN || "",
                },
            })
                .then(function (response) {
                    return response.json().then(function (data) {
                        return { ok: response.ok, data: data };
                    });
                })
                .then(function (result) {
                    const warnings = Array.isArray(result.data.warnings) ? result.data.warnings : [];
                    const baseMessage = warnings.length
                        ? warnings.join(" ")
                        : (result.data.message || "日记已保存。");
                    const message = locationNote ? locationNote + " " + baseMessage : baseMessage;

                    if (!result.ok || result.data.status !== "success") {
                        throw new Error(message);
                    }

                    const tone = warnings.length || locationNote ? "warning" : "success";
                    setStatus(message, tone);
                    rememberStatus(message, tone);
                    window.location.reload();
                })
                .catch(function (error) {
                    submitButton.disabled = false;
                    setStatus(error.message || "日记暂时没有保存成功。", "error");
                });
        };

        if (form.dataset.needsLocation !== "true") {
            sendForm();
            return;
        }

        if (window.isSecureContext && navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                function (position) {
                    latitude.value = position.coords.latitude;
                    longitude.value = position.coords.longitude;
                    accuracy.value = position.coords.accuracy;
                    sendForm();
                },
                function (error) {
                    locationNote = "未取得定位，仍会保存日记。" + describeGeolocationError(error);
                    console.warn("diary geolocation failed", error);
                    setStatus(locationNote, "warning");
                    sendForm();
                },
                {
                    enableHighAccuracy: true,
                    timeout: 10000,
                    maximumAge: 0,
                }
            );
        } else {
            setStatus("当前环境无法定位，仍会保存日记。", "warning");
            sendForm();
        }
    });
})();
