import type { Metadata } from "next";
import type React from "react";
import Link from "next/link";
import { Fraunces, Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const sans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const display = Fraunces({
  variable: "--font-display",
  subsets: ["latin"],
  axes: ["opsz", "SOFT"],
});

export const metadata: Metadata = {
  title: "Ask India",
  description:
    "Plain-English questions about India, answered from official government datasets — with the SQL, the dataset and its vintage shown every time.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${sans.variable} ${mono.variable} ${display.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <header className="border-b border-border/60 bg-background/80 backdrop-blur sticky top-0 z-10">
          <div className="mx-auto flex max-w-5xl items-center justify-between px-5 py-3">
            <Link href="/" className="flex items-baseline gap-2">
              <span className="font-display text-2xl font-semibold tracking-tight">Ask India</span>
              <span className="hidden text-xs text-muted-foreground sm:inline">
                answers from official data, receipts included
              </span>
            </Link>
            <nav className="flex items-center gap-4 text-sm">
              <Link href="/datasets" className="text-muted-foreground hover:text-foreground">
                Datasets
              </Link>
              <a
                href="https://github.com/astrohimanshu/ask-india"
                className="text-muted-foreground hover:text-foreground"
              >
                Source
              </a>
            </nav>
          </div>
        </header>
        <div className="flex flex-1 flex-col">{children}</div>
      </body>
    </html>
  );
}
