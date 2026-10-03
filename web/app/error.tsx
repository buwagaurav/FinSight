"use client";

import Link from "next/link";

/** Shown when a page crashes. Never shows the error's message or stack (they can contain internal details); the
 * digest is an opaque reference that matches the server log. */
export default function Error({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return (
    <div className="max-w-md mx-auto text-center py-16">
      <h1 className="text-xl font-semibold">Something went wrong</h1>
      <p className="mt-2 text-sm text-ink-2">This page hit an unexpected problem. Please try again; if it keeps happening, come back in a few minutes.</p>
      {error.digest && <p className="mt-2 text-xs text-muted">Reference: {error.digest}</p>}
      <div className="mt-6 flex justify-center gap-3">
        <button type="button" onClick={() => retry()} className="rounded-lg bg-accent text-white text-sm font-medium px-4 py-2 hover:opacity-90">Try again</button>
        <Link href="/home" className="rounded-lg border border-line text-sm px-4 py-2 text-ink-2 hover:border-accent hover:text-accent">Go home</Link>
      </div>
    </div>
  );
}
