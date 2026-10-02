import { describe, expect, it } from "vitest";
import { lakhCrore, lumpSum, lumpSumByYear, sip, sipByYear } from "@/lib/sip";

describe("sip", () => {
  it("matches SEBI's calculator at its defaults (₹5,000 a month, 12%, 15 years)", () => {
    const r = sip(5000, "monthly", 12, 15)!;
    expect(r.invested).toBe(900000);
    expect(r.futureValue).toBeCloseTo(2497901.0, 0);   // FV = 5000 × (1.01^180 − 1) / 0.01
    expect(lakhCrore(r.invested)).toBe("₹9.00 Lakh");
    expect(lakhCrore(r.futureValue)).toBe("₹24.98 Lakh");
  });

  it("compounds quarterly instalments at a quarter of the annual rate", () => {
    const r = sip(15000, "quarterly", 12, 10)!;
    expect(r.invested).toBe(600000);
    expect(r.futureValue).toBeCloseTo(15000 * (1.03 ** 40 - 1) / 0.03, 4);
  });

  it("rejects amounts and durations that aren't positive numbers", () => {
    expect(sip(0, "monthly", 12, 15)).toBeNull();
    expect(sip(5000, "monthly", 12, 0)).toBeNull();
    expect(sip(Number.NaN, "monthly", 12, 15)).toBeNull();
  });

  it("gives the year-end value for every year, ending at the full result", () => {
    const years = sipByYear(5000, "monthly", 12, 15);
    expect(years).toHaveLength(15);
    expect(years[14].futureValue).toBeCloseTo(sip(5000, "monthly", 12, 15)!.futureValue, 6);
    expect(years[0].invested).toBe(60000);
  });

  it("formats in lakh and crore", () => {
    expect(lakhCrore(60000)).toBe("₹60,000");
    expect(lakhCrore(12345678)).toBe("₹1.23 Cr");
  });
});

describe("lumpSum", () => {
  it("compounds a one-time amount yearly", () => {
    const r = lumpSum(100000, 12, 10)!;
    expect(r.invested).toBe(100000);
    expect(r.futureValue).toBeCloseTo(100000 * 1.12 ** 10, 6);   // ₹3.11 Lakh
    expect(lakhCrore(r.futureValue)).toBe("₹3.11 Lakh");
  });

  it("keeps the amount invested flat year by year while the value grows", () => {
    const years = lumpSumByYear(100000, 12, 3);
    expect(years.map((y) => y.invested)).toEqual([100000, 100000, 100000]);
    expect(years[2].futureValue).toBeCloseTo(140492.8, 1);
  });

  it("rejects amounts that aren't positive", () => {
    expect(lumpSum(0, 12, 10)).toBeNull();
  });
});
