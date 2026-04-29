function trimAsciiWhitespace(value) {
    return value.replace(/^[ \t\r\f\v]+|[ \t\r\f\v]+$/g, '');
}

// 渲染 Markdown 预览
function renderMarkdownPreview(markdownContentId, previewContainerId) {
    // 获取隐藏的 Markdown 文本
    const markdownElement = document.getElementById(markdownContentId);
    const previewElement = document.getElementById(previewContainerId);

    if (!markdownElement || !previewElement) {
        return;
    }

    const markdownContent = markdownElement.value;
    const maxLines = Number(markdownElement.dataset.previewLines || 5);

    // 按行分割 Markdown 内容
    const lines = markdownContent.split('\n');

    // 提取前几行，跳过开头空行，遇到表格停止
    const previewLines = [];
    for (let i = 0; i < lines.length && previewLines.length < maxLines; i++) {
        const line = lines[i];
        const controlLine = trimAsciiWhitespace(line);

        if (!controlLine && previewLines.length === 0) {
            continue;
        }

        // 如果遇到表格（以 | 开头或包含 |），停止处理
        if (controlLine.startsWith('|') || controlLine.includes('|')) {
            break;
        }

        // 如果是标题（以 # 开头），只保留标题文本
        if (controlLine.startsWith('#')) {
            previewLines.push(controlLine.replace(/^#+[ \t]*/, '')); // 去掉 # 和前面的空格
        } else {
            previewLines.push(line);
        }
    }

    // 将提取的内容合并为 Markdown 文本
    const previewMarkdown = previewLines.join('\n');

    // 使用 marked.js 渲染提取的 Markdown 为 HTML
    previewElement.innerHTML = marked.parse(previewMarkdown);
}
