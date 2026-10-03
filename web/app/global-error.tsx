"use client";

/** Last-resort page when the whole layout fails. Plain HTML and inline styles: the app's own styles may not load. */
export default function GlobalError({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", display: "grid", placeItems: "center", minHeight: "100vh", margin: 0, padding: 16 }}>
        <title>FinSight</title>
        <div style={{ maxWidth: 420, textAlign: "center" }}>
          <h1 style={{ fontSize: 20 }}>Something went wrong</h1>
          <p style={{ fontSize: 14, color: "#52514e" }}>FinSight hit an unexpected problem. Please try again in a moment.</p>
          {error.digest && <p style={{ fontSize: 12, color: "#7d7b75" }}>Reference: {error.digest}</p>}
          <button type="button" onClick={() => retry()} style={{ marginTop: 16, padding: "10px 18px", borderRadius: 8, border: 0, background: "#2a78d6", color: "#fff", fontSize: 14 }}>
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
