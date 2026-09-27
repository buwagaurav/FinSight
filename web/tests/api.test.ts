import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Call = { url: string; init?: RequestInit };

function mockFetch(routes: Record<string, () => Response>) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const handler = routes[url];
    if (!handler) throw new Error(`unexpected fetch ${url}`);
    return handler();
  }));
  return calls;
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

// lib/api caches the sign-in token in module state, so each test gets a fresh copy
async function load() {
  vi.resetModules();
  return import("@/lib/api");
}

beforeEach(() => vi.useFakeTimers({ now: new Date("2026-09-28T10:00:00Z") }));
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("api()", () => {
  it("sends no token for public requests", async () => {
    const calls = mockFetch({ "/api/health": () => json({ ok: true }) });
    const { api } = await load();
    expect(await api("/api/health")).toEqual({ ok: true });
    expect(calls).toHaveLength(1);
    expect((calls[0].init?.headers as Record<string, string>).authorization).toBeUndefined();
  });

  it("attaches the sign-in token and reuses it until it nearly expires", async () => {
    let issued = 0;
    const calls = mockFetch({
      "/auth-token": () => json({ token: `t${++issued}`, expires_at: Date.now() + 3_600_000 }),
      "/api/watchlist/symbols": () => json(["TCS"]),
    });
    const { api } = await load();
    await api("/api/watchlist/symbols", undefined, { auth: true });
    await api("/api/watchlist/symbols", undefined, { auth: true });
    const auth = calls.filter((c) => c.url !== "/auth-token").map((c) => (c.init?.headers as Record<string, string>).authorization);
    expect(auth).toEqual(["Bearer t1", "Bearer t1"]);

    vi.setSystemTime(Date.now() + 3_550_000);            // under a minute left: fetch a fresh one
    await api("/api/watchlist/symbols", undefined, { auth: true });
    expect((calls.at(-1)!.init?.headers as Record<string, string>).authorization).toBe("Bearer t2");
  });

  it("works without a token when sign-in isn't configured (local development)", async () => {
    const calls = mockFetch({
      "/auth-token": () => json({ error: "Sign-in is not configured" }, 503),
      "/api/watchlist": () => json({ items: [] }),
    });
    const { api } = await load();
    expect(await api("/api/watchlist", undefined, { auth: true })).toEqual({ items: [] });
    expect((calls[1].init?.headers as Record<string, string>).authorization).toBeUndefined();
  });

  it("turns API errors into readable messages", async () => {
    mockFetch({
      "/api/a": () => json({ detail: "Your watchlist is full (50 stocks). Remove one to add another." }, 409),
      "/api/b": () => json({ detail: [{ loc: ["body", "note"], msg: "String should have at most 200 characters" }] }, 422),
      "/api/c": () => new Response("Bad gateway", { status: 502 }),
    });
    const { api } = await load();
    await expect(api("/api/a")).rejects.toThrow("Your watchlist is full (50 stocks). Remove one to add another.");
    await expect(api("/api/b")).rejects.toThrow("Invalid request: String should have at most 200 characters");
    await expect(api("/api/c")).rejects.toThrow("Request failed (502)");
  });
});
