import Link from "next/link";

export default function NotFound() {
  return (
    <div className="max-w-md mx-auto text-center py-16">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <p className="mt-2 text-sm text-ink-2">That page doesn&apos;t exist. Search for a stock or fund from the home page.</p>
      <Link href="/home" className="mt-6 inline-block rounded-lg bg-accent text-white text-sm font-medium px-4 py-2 hover:opacity-90">Go home</Link>
    </div>
  );
}
