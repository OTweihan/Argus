import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";

let mdInstance: MarkdownIt | null = null;

function getRenderer(): MarkdownIt {
    if (!mdInstance) {
        // 仍然禁掉 raw HTML 作为一道防线；DOMPurify 作为出口处第二道防线，
        // 双保险防止未来 markdown-it 插件引入新 HTML 注入向量。
        mdInstance = new MarkdownIt({
            html: false,
            breaks: true,
            linkify: true,
        });
    }
    return mdInstance;
}

/**
 * Hook 一次：对 DOMPurify 完成 sanitize 后再过一遍，强制：
 * - `target=_blank` 链接附加 `rel="noopener noreferrer"`
 * - 阻断 `javascript:` / `data:` 协议（DOMPurify 默认会处理，但 linkify
 *   生成的 anchor 标签需要额外保险）。
 *
 * 这段只在模块第一次 import 时跑一次，幂等。
 */
let purifyHookInstalled = false;
function ensurePurifyHook(): void {
    if (purifyHookInstalled) return;
    purifyHookInstalled = true;
    DOMPurify.addHook("afterSanitizeAttributes", (node) => {
        if (!(node instanceof Element)) return;
        if (node.tagName === "A") {
            const href = node.getAttribute("href") || "";
            // 仅允许 http(s) / 相对链接 / 锚点
            if (!/^(https?:|\/|#|mailto:)/i.test(href)) {
                node.removeAttribute("href");
            }
            if (node.hasAttribute("target")) {
                node.setAttribute("rel", "noopener noreferrer");
            }
        }
    });
}

/**
 * 渲染 markdown 文本为 HTML。空字符串返回空串，调用方可据此决定是否显示占位符。
 *
 * 输出已经过 DOMPurify 二次净化（仅保留 markdown 友好的标签子集，剥离
 * script / iframe / on* 事件 / 危险协议链接等）。
 */
export function renderMarkdown(text: string | null | undefined): string {
    if (!text || !text.trim()) return "";
    ensurePurifyHook();
    const raw = getRenderer().render(text);
    return DOMPurify.sanitize(raw, {
        // 白名单仅保留 markdown 常见标签
        ALLOWED_TAGS: [
            "a", "p", "br", "hr", "strong", "em", "del", "s", "ins",
            "blockquote", "code", "pre",
            "ul", "ol", "li",
            "h1", "h2", "h3", "h4", "h5", "h6",
            "table", "thead", "tbody", "tr", "th", "td",
            "img", "span",
        ],
        ALLOWED_ATTR: ["href", "target", "rel", "title", "alt", "src", "class"],
        // 禁掉 data:, vbscript:, javascript: 等危险协议
        ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto):|[#/]|$)/i,
    });
}
