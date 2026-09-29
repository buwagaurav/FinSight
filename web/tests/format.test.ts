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

describe("US listings", () => {
  it("detects the market from the symbol", async () => {
    const { currencyOf } = await import("@/lib/format");
    expect(currencyOf("AAPL.US")).toBe("USD");
    expect(currencyOf("brk-b.us")).toBe("USD");
    expect(currencyOf("TCS.NS")).toBe("INR");
    expect(currencyOf(null)).toBe("INR");
  });

  it("formats dollar prices and $-million amounts", async () => {
    const { amount, money } = await import("@/lib/format");
    expect(money(228.586, "USD")).toBe("$228.59");
    expect(money(1234567, "USD", 0)).toBe("$1,234,567");
    expect(money(-3.5, "USD")).toBe("-$3.50");
    expect(money(2082, "INR", 0)).toBe("₹2,082");
    expect(amount(5_520_000, "USD")).toBe("$5.52 T");
    expect(amount(416_161, "USD")).toBe("$416.2 B");
    expect(amount(950, "USD")).toBe("$950 M");
    expect(amount(-12_500, "USD")).toBe("-$12.5 B");
    expect(amount(753285.78, "INR")).toBe("₹7.53 L Cr");
    expect(amount(null, "USD")).toBe(DASH);
  });
});
