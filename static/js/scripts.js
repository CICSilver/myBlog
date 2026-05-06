const THEME_STORAGE_KEY = "silver-blog-theme";
const THEME_VALUES = ["light", "dark"];

function isValidTheme(theme) {
    return THEME_VALUES.includes(theme);
}

function getStoredTheme() {
    try {
        const theme = window.localStorage.getItem(THEME_STORAGE_KEY);
        return isValidTheme(theme) ? theme : null;
    } catch (error) {
        return null;
    }
}

function setStoredTheme(theme) {
    try {
        window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch (error) {
        return;
    }
}

function getSystemTheme() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function updateThemeControls(theme) {
    const nextTheme = theme === "dark" ? "light" : "dark";
    const label = nextTheme === "dark" ? "切换到深色模式" : "切换到浅色模式";

    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
        button.setAttribute("aria-label", label);
        button.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
        button.setAttribute("title", label);
        button.dataset.themeState = theme;
    });

    document.querySelectorAll("[data-theme-toggle-label]").forEach((labelNode) => {
        labelNode.textContent = label;
    });
}

function applyTheme(theme, shouldPersist = false) {
    const nextTheme = isValidTheme(theme) ? theme : "light";

    document.documentElement.dataset.theme = nextTheme;
    document.documentElement.style.colorScheme = nextTheme;

    if (shouldPersist) {
        setStoredTheme(nextTheme);
    }

    updateThemeControls(nextTheme);
}

function initThemeToggle() {
    applyTheme(getStoredTheme() || document.documentElement.dataset.theme || getSystemTheme());

    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
        button.addEventListener("click", () => {
            const currentTheme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
            applyTheme(currentTheme === "dark" ? "light" : "dark", true);
        });
    });

    if (window.matchMedia) {
        const systemThemeQuery = window.matchMedia("(prefers-color-scheme: dark)");
        const handleSystemThemeChange = (event) => {
            if (!getStoredTheme()) {
                applyTheme(event.matches ? "dark" : "light");
            }
        };

        if (typeof systemThemeQuery.addEventListener === "function") {
            systemThemeQuery.addEventListener("change", handleSystemThemeChange);
        } else if (typeof systemThemeQuery.addListener === "function") {
            systemThemeQuery.addListener(handleSystemThemeChange);
        }
    }
}

document.addEventListener("DOMContentLoaded", initThemeToggle);

function initAdminBookmarkMenu() {
    const triggers = Array.from(document.querySelectorAll("[data-admin-bookmark-trigger]"));

    if (!triggers.length) {
        return;
    }

    function getMenu(trigger) {
        const menuId = trigger.getAttribute("aria-controls");
        if (menuId) {
            return document.getElementById(menuId);
        }

        return trigger.parentElement ? trigger.parentElement.querySelector("[data-admin-bookmark-menu]") : null;
    }

    function closeMenu(trigger) {
        const menu = getMenu(trigger);
        if (!menu) {
            return;
        }

        menu.hidden = true;
        trigger.setAttribute("aria-expanded", "false");
    }

    function closeAllMenus(exceptTrigger = null) {
        triggers.forEach((trigger) => {
            if (trigger !== exceptTrigger) {
                closeMenu(trigger);
            }
        });
    }

    triggers.forEach((trigger) => {
        const menu = getMenu(trigger);
        if (!menu) {
            return;
        }

        trigger.addEventListener("click", (event) => {
            event.stopPropagation();
            const shouldOpen = trigger.getAttribute("aria-expanded") !== "true";

            closeAllMenus(trigger);
            menu.hidden = !shouldOpen;
            trigger.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
        });

        menu.addEventListener("click", (event) => {
            event.stopPropagation();
        });
    });

    document.addEventListener("click", () => {
        closeAllMenus();
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeAllMenus();
        }
    });
}

document.addEventListener("DOMContentLoaded", initAdminBookmarkMenu);

function navigateToWriting() {
    window.location.href = '/edit';
}

function navigateToManage() {
    window.location.href = '/manage';
}

class Modal {
    constructor() {
        this.modalOverlay = document.getElementById("myModalOverlay");
        this.modal = document.getElementById("myModal");
        this.modalHeader = document.getElementById("modal-header");
        this.modalBody = document.getElementById("modal-body-content");
        this.modalHiddenContent = document.getElementById("modal-hidden-content");
        this.modalFooter = document.getElementById("modal-footer");

        if (this.modalOverlay) {
            this.modalOverlay.addEventListener("click", (event) => {
                if (event.target === this.modalOverlay) {
                    this.close();
                }
            });
        }
    }

    show(modalMsg) {
        if (!this.modalOverlay || !this.modal) {
            return;
        }

        if (modalMsg && this.modalBody) {
            this.modalBody.replaceChildren();
            const paragraph = document.createElement("p");
            paragraph.textContent = modalMsg;
            this.modalBody.appendChild(paragraph);
        }

        this.modalOverlay.style.display = "block";
        document.body.classList.add("modal-open");

        requestAnimationFrame(() => {
            this.modalOverlay.classList.add("is-visible");
            this.modal.classList.add("is-visible");
        });
    }

    close() {
        if (!this.modalOverlay || !this.modal) {
            return;
        }

        this.modalOverlay.classList.remove("is-visible");
        this.modal.classList.remove("is-visible");
        document.body.classList.remove("modal-open");

        setTimeout(() => {
            this.modalOverlay.style.display = "none";
        }, 220);
    }

    setTitle(title) {
        if (this.modalHeader) {
            this.modalHeader.replaceChildren();
            const heading = document.createElement("h2");
            heading.textContent = title;
            this.modalHeader.appendChild(heading);
        }
    }

    setHiddenValue(value) {
        if (this.modalHiddenContent) {
            this.modalHiddenContent.textContent = value;
        }
    }

    getHiddenValue() {
        return this.modalHiddenContent ? this.modalHiddenContent.textContent : "";
    }

    addButton(btnText, onClickFunction, tone = "default") {
        if (this.modalFooter) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "modal-btn";
            if (tone === "secondary") {
                btn.classList.add("is-secondary");
            } else if (tone === "danger") {
                btn.classList.add("is-danger");
            }
            btn.innerText = btnText;
            btn.onclick = onClickFunction;

            this.modalFooter.appendChild(btn);
        }
    }

    clearButtons() {
        if (this.modalFooter) {
            this.modalFooter.innerHTML = "";
        }
    }
}

async function logout() {
    fetch('/logout', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': window.BLOG_CSRF_TOKEN || ''
        }
    })
        .then(response => response.json())
        .then(data => {
            if (data.status === "success") {
                window.location.href = '/';
            } else {
                alert(data.message);
            }
        });
}
