import type { Metadata } from "next";
import { Geist } from "next/font/google";
import Link from "next/link";
import Nav from "@/components/Nav";
import { UserProvider } from "@/components/UserContext";
import { WatchlistProvider } from "@/components/WatchlistContext";
import { authEnabled, currentUser } from "@/auth";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "FinSight",
  description: "Stocks, fundamentals, screening and IPOs in one research workspace.",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const user = await currentUser();
  return (
    <html lang="en" className={`${geistSans.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col font-sans">
        <UserProvider user={user} authEnabled={authEnabled}>
        <WatchlistProvider>
        <Nav />
        <main className="flex-1 w-full max-w-[1440px] mx-auto px-4 sm:px-6 py-6">{children}</main>
        <footer className="border-t border-line text-xs text-muted">
          <div className="max-w-[1440px] mx-auto px-4 sm:px-6 py-4 flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
            <p>
              FinSight is a research tool, not investment advice. Data from NSE and Yahoo Finance may be delayed or
              incomplete; verify important figures against company filings.
            </p>
            <nav aria-label="Legal" className="flex gap-4 shrink-0">
              <Link href="/privacy" className="hover:text-ink underline-offset-4 hover:underline">Privacy Policy</Link>
              <Link href="/terms" className="hover:text-ink underline-offset-4 hover:underline">Terms of Use</Link>
            </nav>
          </div>
        </footer>
        </WatchlistProvider>
        </UserProvider>
      </body>
    </html>
  );
}
