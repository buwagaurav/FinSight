const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const DASH = "—";

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
