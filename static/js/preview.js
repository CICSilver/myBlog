// 渲染 Markdown 预览
function renderMarkdownPreview(markdownContentId, previewContainerId) {
    // 获取隐藏的 Markdown 文本
    const markdownContent = document.getElementById(markdownContentId).value;

    // 按行分割 Markdown 内容
    const lines = markdownContent.split('\n');

    // 提取前五行，遇到表格停止
    const previewLines = [];
    for (let i = 0; i < lines.length && previewLines.length < 5; i++) {
        const line = lines[i].trim();

        // 如果遇到表格（以 | 开头或包含 |），停止处理
        if (line.startsWith('|') || line.includes('|')) {
            break;
        }

        // 如果是标题（以 # 开头），只保留标题文本
        if (line.startsWith('#')) {
            previewLines.push(line.replace(/^#+\s*/, '')); // 去掉 # 和前面的空格
        } else {
            previewLines.push(line);
        }
    }

    // 将提取的内容合并为 Markdown 文本
    const previewMarkdown = previewLines.join('\n');

    // 使用 marked.js 渲染提取的 Markdown 为 HTML
    document.getElementById(previewContainerId).innerHTML = marked.parse(previewMarkdown);
}