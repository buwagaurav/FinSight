/** SIP (systematic investment plan) maths, matching SEBI's investor calculator
 * (investor.sebi.gov.in/calculators/sip_calculator.html): the future value of a fixed instalment paid at the end of
 * each period, with the annual return split evenly across periods (12% a year = 1% a month).
 *
 *   FV = P × ((1 + r)^n − 1) / r,   r = annual % ÷ 100 ÷ periods per year,   n = periods per year × years
 */

export type Frequency = "monthly" | "quarterly";
export const PERIODS: Record<Frequency, number> = { monthly: 12, quarterly: 4 };

// The same limits as SEBI's calculator
export const LIMITS = {
  amount: { min: 100, max: 500000, step: 100, initial: 5000 },
  rate: { min: 1, max: 30, step: 0.1, initial: 12 },
  years: { min: 1, max: 50, step: 1, initial: 15 },
};

export type SipResult = { invested: number; futureValue: number; gains: number };

export function sip(amount: number, frequency: Frequency, annualRatePct: number, years: number): SipResult | null {
  if (![amount, annualRatePct, years].every(Number.isFinite) || amount <= 0 || years <= 0) return null;
  const per = PERIODS[frequency];
  const n = per * years;
  const r = annualRatePct / 100 / per;
  const futureValue = r === 0 ? amount * n : amount * ((1 + r) ** n - 1) / r;
  const invested = amount * n;
  return { invested, futureValue, gains: futureValue - invested };
}

/** Value at the end of each year, for the growth chart. */
export function sipByYear(amount: number, frequency: Frequency, annualRatePct: number, years: number) {
  return Array.from({ length: Math.floor(years) }, (_, i) => ({ year: i + 1, ...sip(amount, frequency, annualRatePct, i + 1)! }));
}

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

/** ₹ amounts the way SEBI's calculator shows them: "₹24.98 Lakh", "₹1.23 Cr", "₹60,000". */
export function lakhCrore(v: number): string {
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)} Lakh`;
  return `₹${inr.format(Math.round(v))}`;
}
