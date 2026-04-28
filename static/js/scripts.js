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
