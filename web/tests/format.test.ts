import { describe, expect, it } from "vitest";
import { crore, DASH, num, pct, rupees, tone } from "@/lib/format";

describe("format", () => {
  it("formats rupees the Indian way", () => {
    expect(rupees(123456.789)).toBe("₹1,23,456.79");
    expect(rupees(2082, 0)).toBe("₹2,082");
    expect(rupees(null)).toBe(DASH);
  });

  it("shows large crore amounts as lakh crore", () => {
    expect(crore(753285.78)).toBe("₹7.53 L Cr");
    expect(crore(49210)).toBe("₹49,210 Cr");
    expect(crore(-150000)).toBe("₹-1.50 L Cr");
    expect(crore(undefined)).toBe(DASH);
  });

  it("formats percentages and plain numbers", () => {
    expect(pct(48.7234)).toBe("48.7%");
    expect(pct(2.5, 1, true)).toBe("+2.5%");
    expect(pct(-2.5, 1, true)).toBe("-2.5%");
    expect(pct(0)).toBe("0.0%");            // zero is a value, not missing
    expect(num(15.128, 1, "x")).toBe("15.1x");
    expect(num(null)).toBe(DASH);
  });

  it("maps score labels to colours", () => {
    expect(tone("Strong")).toBe("good");
    expect(tone("Improving")).toBe("good");
    expect(tone("Watchlist")).toBe("warn");
    expect(tone("Weak")).toBe("bad");
    expect(tone("Not enough data")).toBe("neutral");
  });
});
