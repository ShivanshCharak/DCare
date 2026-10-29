import type { Metadata } from "next";
import "./globals.css";
import { ApiAccessToken } from "./components/ApiAccessToken";

export const metadata: Metadata = {
  title: "Discharge Explainer",
  description: "Source-grounded discharge summary explanation demo"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <ApiAccessToken />
        {children}
      </body>
    </html>
  );
}
