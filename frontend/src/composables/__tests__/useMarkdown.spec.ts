import { describe, expect, it } from "vitest";

import { renderMarkdown } from "../useMarkdown";

/**
 * P0-4 验证：useMarkdown 输出经 DOMPurify 净化，常见 XSS 向量都应被剥离。
 *
 * markdown-it 默认 `html: false` 已经过滤裸 HTML，但 linkify / 未来插件可能
 * 引入新向量；DOMPurify 是出口处第二道防线。
 */
describe("renderMarkdown XSS hardening", () => {
    it("renders normal markdown content", () => {
        const html = renderMarkdown("**bold** *em* `code`");
        expect(html).toContain("<strong>");
        expect(html).toContain("<em>");
        expect(html).toContain("<code>");
    });

    it("returns empty string for null/empty input", () => {
        expect(renderMarkdown(null)).toBe("");
        expect(renderMarkdown(undefined)).toBe("");
        expect(renderMarkdown("")).toBe("");
        expect(renderMarkdown("   \n\t  ")).toBe("");
    });

    it("strips script tags injected via raw HTML", () => {
        const html = renderMarkdown('<script>alert("xss")</script>hello');
        // markdown-it html:false 已经转义，但仍做出口断言：没生成可执行 <script>
        expect(html.toLowerCase()).not.toMatch(/<script[\s>]/);
        expect(html).toContain("hello");
    });

    it("strips inline event handlers on <a> elements", () => {
        // 即便有人直接塞 raw HTML <a onmouseover="...">，DOMPurify 也会剥光
        const html = renderMarkdown('<a href="#" onmouseover="alert(1)">x</a>');
        expect(html.toLowerCase()).not.toMatch(/<a[^>]*onmouseover/);
    });

    it("strips dangerous attributes from injected img tags", () => {
        const html = renderMarkdown('<img src=x onerror="alert(1)">');
        expect(html.toLowerCase()).not.toMatch(/<img[^>]*onerror/);
    });

    it("blocks javascript: URLs in links (no <a href> emitted)", () => {
        const html = renderMarkdown('[evil](javascript:alert(1))');
        // 关键断言：不能生成 `<a href="javascript:...">`，即使字面量里残留也无害
        expect(html.toLowerCase()).not.toMatch(/<a[^>]*href=["']javascript:/);
        expect(html).toContain("evil");
    });

    it("blocks data: URLs in images (no <img src=data:> emitted)", () => {
        const html = renderMarkdown('![evil](data:text/html,<script>)');
        // 关键断言：不能生成 `<img src="data:...">`，即使字面量里残留也无害
        expect(html.toLowerCase()).not.toMatch(/<img[^>]*src=["']data:/);
    });

    it("strips iframe and object tags", () => {
        const html = renderMarkdown('<iframe src="x"></iframe><object data="x"></object>');
        expect(html.toLowerCase()).not.toContain("<iframe");
        expect(html.toLowerCase()).not.toContain("<object");
    });

    it("keeps safe http link unchanged", () => {
        const html = renderMarkdown("[home](https://example.com)");
        expect(html).toContain('href="https://example.com"');
    });

    it("renders code blocks safely", () => {
        const html = renderMarkdown("```\n<script>alert(1)</script>\n```");
        // code block 内部的尖括号应被转义，而非作为标签解析
        expect(html).toContain("<pre>");
        expect(html.toLowerCase()).not.toMatch(/<script[^&]/);
    });
});
