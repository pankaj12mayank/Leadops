import { useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { SOURCES } from "@/lib/types";
import { startScraper } from "@/lib/api";
import { toast } from "@/hooks/use-toast";
import { Loader2, Search } from "lucide-react";

interface SearchSectionProps {
  onJobStarted: (jobId: number) => void;
  heading?: string;
  subtitle?: string;
  labels?: { source?: string; keyword?: string; location?: string; maxPages?: string };
  placeholders?: { keyword?: string; location?: string };
  buttonLabel?: string;
}

export default function SearchSection({
  onJobStarted,
  heading = "Extract Leads",
  subtitle = "Choose a source and enter your search criteria",
  labels = {},
  placeholders = {},
  buttonLabel = "Scrape",
}: SearchSectionProps) {
  const [source, setSource] = useState("clutch");
  const [keyword, setKeyword] = useState("");
  const [location, setLocation] = useState("");
  const [maxPages, setMaxPages] = useState("5");
  const [submitting, setSubmitting] = useState(false);

  const mergedLabels = { source: "Source", keyword: "Keyword", location: "Location (optional)", maxPages: "Max Pages", ...labels };
  const mergedPlaceholders = { keyword: "e.g. marketing agencies", location: "e.g. New York", ...placeholders };

  const handleScrape = useCallback(async () => {
    if (!keyword.trim()) {
      toast({ title: "Missing keyword", description: "Enter a search keyword", variant: "destructive" });
      return;
    }
    setSubmitting(true);
    try {
      const body: Record<string, unknown> = { query: keyword.trim(), max_pages: Number(maxPages) || 5 };
      if (source === "maps" && location.trim()) {
        body.query = `${keyword.trim()} ${location.trim()}`;
      }
      const res = await startScraper(source, body);
      toast({ title: "Job queued", description: `${source}: job #${res.job_id}` });
      onJobStarted(res.job_id);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to start";
      toast({ title: "Error", description: msg, variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  }, [source, keyword, location, maxPages, onJobStarted]);

  return (
    <section id="search" className="py-16 md:py-24">
      <div className="mx-auto max-w-2xl px-4">
        <h2 className="text-2xl md:text-3xl font-bold text-center mb-2">{heading}</h2>
        <p className="text-muted-foreground text-center mb-8 text-sm">{subtitle}</p>

        <div className="space-y-4">
          <div>
            <label className="text-sm font-medium mb-1.5 block">{mergedLabels.source}</label>
            <select
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {SOURCES.map((s) => (
                <option key={s.id} value={s.id}>{s.label}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-sm font-medium mb-1.5 block">{mergedLabels.keyword}</label>
            <input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder={mergedPlaceholders.keyword}
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          <div>
            <label className="text-sm font-medium mb-1.5 block">{mergedLabels.location}</label>
            <input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder={mergedPlaceholders.location}
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          <div>
            <label className="text-sm font-medium mb-1.5 block">{mergedLabels.maxPages}</label>
            <input
              type="number"
              min={1}
              max={100}
              value={maxPages}
              onChange={(e) => setMaxPages(e.target.value)}
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          <Button className="w-full h-11 text-base" disabled={submitting} onClick={handleScrape}>
            {submitting ? (
              <><Loader2 className="h-5 w-5 mr-2 animate-spin" /> Submitting...</>
            ) : (
              <><Search className="h-5 w-5 mr-2" /> {buttonLabel}</>
            )}
          </Button>
        </div>
      </div>
    </section>
  );
}
