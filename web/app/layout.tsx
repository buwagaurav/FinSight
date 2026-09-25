import type { Metadata } from "next";
import { Geist } from "next/font/google";
import Nav from "@/components/Nav";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "FinSight",
  description: "Stocks, fundamentals, screening and IPOs in one research workspace.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col font-sans">
        <Nav />
        <main className="flex-1 w-full max-w-6xl mx-auto px-4 sm:px-6 py-6">{children}</main>
        <footer className="border-t border-line text-xs text-muted">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 py-4">
            FinSight is a research tool, not investment advice. Data from NSE and Yahoo Finance may be delayed or
            incomplete; verify important figures against company filings.
          </div>
        </footer>
      </body>
    </html>
  );
}
