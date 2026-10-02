// Responsive check: opens each page at phone, tablet and desktop sizes in Chrome and fails if a page scrolls
// sideways, an element sticks out past the screen edge (outside a scrolling table), or the console logs an error.
//
//   npm run dev                  (and the API: see README)
//   npm run audit:responsive     BASE_URL=... PAGES=/,/ipo VIEWPORTS=320x568,390x844 CHROME_PATH=... to override
//
// Uses your installed Chrome (or CHROME_PATH); playwright-core downloads no browser.
import { chromium } from "playwright-core";

const BASE = process.env.BASE_URL || "http://localhost:3000";
const VIEWPORTS = (process.env.VIEWPORTS ||
  "320x568,360x800,390x844,430x932,600x960,768x1024,1024x1366,1280x800,1440x900,1920x1080,844x390,1024x768").split(",");
const PAGES = (process.env.PAGES ||
  "/,/home,/stock/TCS.NS,/stock/TCS.NS#Fundamentals,/stock/TCS.NS#Valuation,/stock/TCS.NS#Filings & news,/stock/TCS.NS#AI report,/screener,/ipo,/sip,/funds,/funds/122639,/privacy,/terms").split(",");

const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : { channel: "chrome" });
let failures = 0;
for (const vp of VIEWPORTS) {
  const [width, height] = vp.split("x").map(Number);
  const touch = width < 1024 || height < width && height < 500;
  const ctx = await browser.newContext({ viewport: { width, height }, hasTouch: touch, isMobile: touch });
  for (const path of PAGES) {
    const page = await ctx.newPage();
    const errors = [];
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 160)); });
    page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
    const [url, tab] = path.split("#");
    await page.goto(BASE + url, { waitUntil: "networkidle", timeout: 120_000 });
    if (tab) {
      await page.getByRole("tab", { name: tab, exact: true }).click();
      await page.waitForLoadState("networkidle");
    }
    await page.waitForTimeout(500);
    const found = await page.evaluate(() => {
      const vw = document.documentElement.clientWidth;
      const scrolls = (el) => {
        for (let p = el.parentElement; p; p = p.parentElement) {
          const s = getComputedStyle(p);
          if (/(auto|scroll|hidden|clip)/.test(s.overflowX) && p !== document.body && p !== document.documentElement) return true;
        }
        return false;
      };
      const outside = [...document.body.querySelectorAll("*")]
        .filter((el) => { const b = el.getBoundingClientRect(); return b.width && b.right > vw + 1 && getComputedStyle(el).position !== "fixed" && !scrolls(el); })
        .slice(0, 5)
        .map((el) => `<${el.tagName.toLowerCase()} class="${String(el.className).slice(0, 60)}">`);
      return { sideways: document.documentElement.scrollWidth - vw, outside };
    });
    const ok = found.sideways <= 0 && !found.outside.length && !errors.length;
    if (!ok) failures++;
    console.log(`${ok ? "ok  " : "FAIL"} ${vp.padEnd(10)} ${path}` +
      (found.sideways > 0 ? `  scrolls sideways by ${found.sideways}px` : "") +
      found.outside.map((o) => `\n       past the edge: ${o}`).join("") +
      errors.map((e) => `\n       console: ${e}`).join(""));
    await page.close();
  }
  await ctx.close();
}
await browser.close();
console.log(failures ? `\n${failures} page/size combinations failed` : "\nAll pages fit at every size.");
process.exit(failures ? 1 : 0);
