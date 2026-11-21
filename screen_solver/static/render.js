// 模型输出是不可信内容：先解析 Markdown，再清理 HTML；不加载远程图片。
function renderMarkdown(element, text) {
  try {
    element.innerHTML = DOMPurify.sanitize(marked.parse(text), {
      USE_PROFILES: {html: true}, FORBID_TAGS: ['img'], FORBID_ATTR: ['style']
    });
  } catch (error) {
    element.textContent = text;
  }
}
