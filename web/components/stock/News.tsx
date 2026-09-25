"use client";

import { useEffect, useState } from "react";
import { Card, Skeleton } from "@/components/ui";
import { api, NewsItem } from "@/lib/api";
import { date } from "@/lib/format";

export default function News({ symbol }: { symbol: string }) {
  const [items, setItems] = useState<NewsItem[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    api<NewsItem[]>(`/api/company/${encodeURIComponent(symbol)}/news`).then(setItems).catch(() => setError(true));
  }, [symbol]);

  return (
    <Card title="Latest news">
      {error && <p className="text-sm text-muted">News is unavailable right now.</p>}
      {!items && !error && <div className="space-y-3"><Skeleton className="h-14" /><Skeleton className="h-14" /><Skeleton className="h-14" /></div>}
      {items?.length === 0 && <p className="text-sm text-muted">No recent news found for this company.</p>}
      <ul className="divide-y divide-line">
        {items?.map((n) => (
          <li key={n.url} className="py-3">
            <a href={n.url} target="_blank" rel="noreferrer" className="font-medium text-sm hover:text-accent">{n.title} ↗</a>
            {n.summary && <p className="text-sm text-ink-2 mt-1 line-clamp-2">{n.summary}</p>}
            <div className="text-xs text-muted mt-1">{n.publisher ?? "Unknown source"} · {date(n.published)}</div>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted mt-3">Headlines from Yahoo Finance. Official exchange filings, with AI summaries, are listed alongside.</p>
    </Card>
  );
}
