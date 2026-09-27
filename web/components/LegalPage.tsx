import { ReactNode } from "react";

export const UPDATED = "27 September 2026";
const EMAIL = process.env.NEXT_PUBLIC_CONTACT_EMAIL;
const REPO = "https://github.com/buwagaurav/FinSight";

/** How to reach FinSight: the support email once NEXT_PUBLIC_CONTACT_EMAIL is set, the GitHub repository until then. */
export function Contact() {
  return EMAIL
    ? <>email <a href={`mailto:${EMAIL}`} className="text-accent underline">{EMAIL}</a></>
    : <>open an issue at <a href={`${REPO}/issues`} className="text-accent underline" target="_blank" rel="noreferrer">github.com/buwagaurav/FinSight</a></>;
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold text-ink">{title}</h2>
      <div className="space-y-3 text-ink-2 leading-relaxed">{children}</div>
    </section>
  );
}

export default function LegalPage({ title, intro, children }: { title: string; intro: string; children: ReactNode }) {
  return (
    <article className="mx-auto max-w-[42rem] py-6 sm:py-10">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-accent">FinSight</p>
      <h1 className="mt-2 text-3xl sm:text-4xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-2 text-sm text-muted">Last updated {UPDATED}</p>
      <p className="mt-6 text-lg text-ink-2 leading-relaxed">{intro}</p>
      <div className="mt-10 space-y-10 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:space-y-1.5">{children}</div>
    </article>
  );
}
