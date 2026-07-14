import DOMPurify from "dompurify";
import { marked } from "marked";

marked.setOptions({ breaks: true, gfm: true });

export function safeMarkdown(value: string): string {
  return DOMPurify.sanitize(marked.parse(value, { async: false }) as string, {
    USE_PROFILES: { html: true },
  });
}
