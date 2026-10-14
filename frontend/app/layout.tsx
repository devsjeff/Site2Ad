import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "site2ad: website to video ad",
  description: "Paste your website and get a short video ad for taxi screens and social media. No design skills needed.",
};

// Root layout: page shell and global styles.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
