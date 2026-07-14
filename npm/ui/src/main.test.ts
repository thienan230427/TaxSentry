import { describe, expect, it } from "vitest";
import { NAV } from "./main";

describe("Control Center navigation", () => {
  it("exposes the six TaxSentry core surfaces once", () => {
    expect(NAV.map(([route]) => route)).toEqual(["overview", "chat", "jobs", "reports", "connections", "settings"]);
    expect(new Set(NAV.map(([, label]) => label)).size).toBe(6);
  });
});
