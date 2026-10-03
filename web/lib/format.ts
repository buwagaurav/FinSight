const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const DASH = "—";

/** A link from outside data (news, filings, user-entered GMP sources), or undefined unless it's plain http(s):
 * a "javascript:" or "data:" link could run code in the reader's browser. */
export function safeUrl(url: string | null | undefined): string | undefined {
  return url && /^https?:\/\//i.test(url.trim()) ? url.trim() : undefined;
}

export function rupees(v: number | null | undefined, decimals = 2): string {
  if (v == null) return DASH;
  return "₹" + (decimals ? inr2.format(v) : inr.format(v));
}

/** Values already in ₹ crore. Large amounts read better as lakh crore. */
export function crore(v: number | null | undefined): string {
  if (v == null) return DASH;
  if (Math.abs(v) >= 100000) return `₹${(v / 100000).toFixed(2)} L Cr`;
  return `₹${inr.format(v)} Cr`;
}

const inr4 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 4 });

/** A mutual fund NAV: up to 4 decimals, as AMFI publishes it. */
export function nav(v: number | null | undefined): string {
  return v == null ? DASH : "₹" + inr4.format(v);
}

export function pct(v: number | null | undefined, decimals = 1, signed = false): string {
  if (v == null) return DASH;
  const s = v.toFixed(decimals) + "%";
  return signed && v > 0 ? "+" + s : s;
}

export function num(v: number | null | undefined, decimals = 1, suffix = ""): string {
  if (v == null) return DASH;
  return v.toFixed(decimals) + suffix;
}

export function date(iso: string | null | undefined): string {
  if (!iso) return DASH;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function tone(label: string): "good" | "warn" | "bad" | "neutral" {
  if (label === "Strong" || label === "Improving") return "good";
  if (label === "Stable") return "neutral";
  if (label === "Watchlist") return "warn";
  if (label === "Weak") return "bad";
  return "neutral";
}

// ---------------------------------------------------------------- Indian (₹) and US ($) listings

export type Currency = "INR" | "USD";

/** US listings end in .US (AAPL.US); everything else is an Indian listing. */
export const currencyOf = (symbol: string | null | undefined): Currency => (symbol?.toUpperCase().endsWith(".US") ? "USD" : "INR");

const usd = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const usd2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** A price or per-share amount in the listing's currency. */
export function money(v: number | null | undefined, cur: Currency = "INR", decimals = 2): string {
  if (cur === "INR") return rupees(v, decimals);
  if (v == null) return DASH;
  return (v < 0 ? "-$" : "$") + (decimals ? usd2.format(Math.abs(v)) : usd.format(Math.abs(v)));
}

/** A company-level amount: ₹ crore for Indian companies, $ millions for US ones (as the API sends them). */
export function amount(v: number | null | undefined, cur: Currency = "INR"): string {
  if (cur === "INR") return crore(v);
  if (v == null) return DASH;
  const a = Math.abs(v), sign = v < 0 ? "-" : "";
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(2)} T`;
  if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(1)} B`;
  return `${sign}$${usd.format(a)} M`;
}

/** Plain number in the unit of a statements table (grouped the Indian or US way). */
export const tableNumber = (v: number, cur: Currency = "INR") => (cur === "USD" ? usd : inr).format(v);
export const amountUnit = (cur: Currency) => (cur === "USD" ? "$ M" : "₹ Cr");
export const currencySign = (cur: Currency) => (cur === "USD" ? "$" : "₹");
