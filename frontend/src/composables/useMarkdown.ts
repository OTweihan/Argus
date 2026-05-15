import MarkdownIt from "markdown-it";

let mdInstance: MarkdownIt | null = null;

function getRenderer(): MarkdownIt {
    if (!mdInstance) {
        mdInstance = new MarkdownIt({
            html: false,
            breaks: true,
            linkify: true,
        });
    }
    return mdInstance;
}

/**
 * 渲染 markdown 文本为 HTML。空字符串返回空串，调用方可据此决定是否显示占位符。
 */
export function renderMarkdown(text: string | null | undefined): string {
    if (!text || !text.trim()) return "";
    return getRenderer().render(text);
}
