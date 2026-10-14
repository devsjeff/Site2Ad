import { AdResult } from "@/components/ad/AdResult";

export const metadata = { title: "Your ad | Adsify" };

// Result page for one ad; the id comes from the URL so a refresh keeps working.
export default function AdPage() {
  return <AdResult />;
}
