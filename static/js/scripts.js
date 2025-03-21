function navigateToWriting() {
    window.location.href = '/edit';
}

document.getElementById('content').addEventListener('keydown', function(event) {
    console.log('keydown', event);
    if(event.key == 'Tab') {
        event.preventDefault();
        const textarea = this;
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        const indent = '  '; // 2 spaces
        // 光标位置插入缩进
        textarea.value = textarea.value.substring(0, start) + indent + textarea.value.substring(end);
        // 更新光标位置
        textarea.selectionStart = textarea.selectionEnd = start + indent.length;
    }
});