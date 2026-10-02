import { describe, expect, it } from "vitest";
import { popoverPosition } from "@/lib/position";

const anchor = (left: number, top = 300) => ({ left, top, width: 16, bottom: top + 16 });

describe("popoverPosition", () => {
  it("centres on the anchor when there's room", () => {
    const p = popoverPosition(anchor(500), 1280);
    expect(p.left).toBe(500 + 8 - 128);
    expect(p.width).toBe(256);
  });

  it("never leaves the screen on a 320px phone, at either edge", () => {
    for (const x of [0, 150, 304]) {
      const p = popoverPosition(anchor(x), 320);
      expect(p.left).toBeGreaterThanOrEqual(8);
      expect(p.left + p.width).toBeLessThanOrEqual(312);
    }
  });

  it("narrows to fit screens slimmer than the popover", () => {
    expect(popoverPosition(anchor(100), 240).width).toBe(224);
  });

  it("opens below the anchor near the top of the screen", () => {
    expect(popoverPosition(anchor(100, 300), 390).above).toBe(true);
    const low = popoverPosition(anchor(100, 60), 390);
    expect(low.above).toBe(false);
    expect(low.top).toBe(60 + 16 + 8);
  });
});
