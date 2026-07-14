import { describe, expect, it } from "vitest";
import { safeMarkdown } from "./security";

describe("safeMarkdown", () => {
  it("renders useful markdown and removes executable markup", () => {
    const html = safeMarkdown("**An toàn** <img src=x onerror=alert(1)> <script>alert(2)</script>");
    expect(html).toContain("<strong>An toàn</strong>");
    expect(html).not.toContain("onerror");
    expect(html).not.toContain("<script");
  });

  it("removes dangerous links", () => {
    expect(safeMarkdown("[bad](javascript:alert(1))")).not.toContain("javascript:");
  });
});
