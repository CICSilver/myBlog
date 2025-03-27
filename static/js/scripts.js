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
    }

    show(modalMsg) {
        if (modalMsg) {
            this.modalBody.innerHTML = `<p>${modalMsg}</p>`;
        }

        // 显示模态窗口的背景
        this.modalOverlay.style.display = "block";
        this.modalOverlay.classList.remove("fade-out");

        // 设置模态窗口的动画效果
        setTimeout(() => {
            this.modal.style.top = "50%"; // 将窗口移动到视口中间
            this.modal.style.opacity = "1"; // 设置透明度为完全可见
        }, 10); // 延迟是为了确保动画生效
    }

    // 关闭模态窗口
    close() {
        this.modalOverlay.classList.add("fade-out");

        // 隐藏模态窗口的动画效果
        this.modal.style.top = "-100%"; // 将窗口移回视口上方
        this.modal.style.opacity = "0"; // 设置透明度为不可见

        // 等待动画结束后隐藏模态窗口的背景
        setTimeout(() => {
            this.modalOverlay.style.display = "none"; // 隐藏背景
        }, 300); // 延迟与 CSS 的 transition 时间一致
    }

    setTitle(title) {
        if (this.modalHeader) {
            this.modalHeader.innerHTML = `<h2>${title}</h2>`;
        }
    }

    // 添加按钮到模态窗口的底部
    addButton(btnText, onClickFunction) {
        if (this.modalFooter) {
            const btn = document.createElement("button");
            btn.className = "grey_btn modal-btn";
            btn.innerText = btnText;
            btn.onclick = onClickFunction;

            this.modalFooter.appendChild(btn);
        }
    }

    // 清空模态窗口底部的按钮
    clearButtons() {
        if (this.modalFooter) {
            this.modalFooter.innerHTML = "";
        }
    }
}


