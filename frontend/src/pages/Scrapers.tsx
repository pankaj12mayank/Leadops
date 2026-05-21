import { useState, useEffect, useCallback, useRef } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { getStatus, startScraper, stopScraper, runMerge, type StatusResponse } from "@/lib/api";
import { SCRAPERS, type ScraperDef } from "@/lib/types";
import { toast } from "@/hooks/use-toast";
import { Play, Merge, Loader2, ExternalLink } from "lucide-react";
import { ErrorState } from "@/components/shared/ErrorState";

export default function Scrapers() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [inputs, setInputs] = useState<Record<string, Record<string, string>>>({});
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [runningScrapers, setRunningScrapers] = useState<Set<string>>(new Set());
  const pollingRef = useRef(false);

  const fetchStatus = useCallback(() => {
    if (pollingRef.current) return;
    pollingRef.current = true;
    getStatus()
      .then((s) => { setStatus(s); setFetchError(null); })
      .catch(() => { if (!status) setFetchError("Failed to connect to backend"); })
      .finally(() => { pollingRef.current = false; setLoading(false); });
  }, [status]);

  useEffect(() => { fetchStatus(); const i = setInterval(fetchStatus, 3000); return () => clearInterval(i); }, [fetchStatus]);

  useEffect(() => {
    if (status) {
      setRunningScrapers(new Set(status.active_sources));
    }
  }, [status]);

  function setInput(scraperId: string, key: string, value: string) {
    setInputs((prev) => ({
      ...prev,
      [scraperId]: { ...(prev[scraperId] || {}), [key]: value },
    }));
  }

  function getInput(def: ScraperDef, key: string): string {
    return inputs[def.id]?.[key] ?? def.inputs.find((i) => i.key === key)?.defaultValue ?? "";
  }

  async function handleStart(scraper: ScraperDef) {
    const body: Record<string, unknown> = {};
    for (const inp of scraper.inputs) {
      const val = getInput(scraper, inp.key);
      if (!val && inp.type === "text" && !inp.defaultValue) {
        toast({ title: "Missing input", description: `${inp.label} is required`, variant: "destructive" });
        return;
      }
      body[inp.key] = inp.type === "number" ? (val === "" ? parseInt(inp.defaultValue) : Number(val)) : val;
    }
    setRunningScrapers((prev) => new Set(prev).add(scraper.id));
    try {
      const res = await startScraper(scraper.id, body);
      toast({ title: "Scraper started", description: `${scraper.label}: ${res.task_id}` });
    } catch (err: unknown) {
      setRunningScrapers((prev) => { const s = new Set(prev); s.delete(scraper.id); return s; });
      const msg = err instanceof Error ? err.message : "Failed to start";
      toast({ title: "Error", description: msg, variant: "destructive" });
    }
  }

  async function handleStop(scraper: ScraperDef) {
    setRunningScrapers((prev) => { const s = new Set(prev); s.delete(scraper.id); return s; });
    try {
      await stopScraper(scraper.id);
      toast({ title: "Stopped", description: `${scraper.label} cancelled` });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to stop";
      toast({ title: "Error", description: msg, variant: "destructive" });
    }
  }

  async function handleMerge() {
    setRunningScrapers((prev) => new Set(prev).add("merge"));
    try {
      const res = await runMerge();
      toast({ title: "Merge started", description: `Task: ${res.task_id}` });
    } catch (err: unknown) {
      setRunningScrapers((prev) => { const s = new Set(prev); s.delete("merge"); return s; });
      const msg = err instanceof Error ? err.message : "Failed to start merge";
      toast({ title: "Error", description: msg, variant: "destructive" });
    }
  }

  const isRunning = (id: string) => runningScrapers.has(id);

  if (fetchError && !status) {
    return <ErrorState message={fetchError} onRetry={fetchStatus} />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Scrapers</h1>
        <p className="text-sm text-muted-foreground mt-1">Start and monitor data extraction jobs</p>
      </div>

      {fetchError && status && (
        <div className="text-xs text-yellow-400 bg-yellow-500/10 border border-yellow-500/30 rounded-md px-3 py-2">
          Status updates stalled — showing last known state
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {SCRAPERS.map((scraper) => (
          <Card key={scraper.id}>
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between">
                <div>
                  <CardTitle className="text-sm">{scraper.label}</CardTitle>
                  <CardDescription className="mt-1">{scraper.description}</CardDescription>
                </div>
                <Badge variant={isRunning(scraper.id) ? "default" : "secondary"}>
                  {isRunning(scraper.id) ? "Running" : "Idle"}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {scraper.inputs.map((inp) => (
                <div key={inp.key}>
                  <label className="text-xs text-muted-foreground mb-1 block">{inp.label}</label>
                  <Input
                    placeholder={inp.defaultValue || `Enter ${inp.label.toLowerCase()}`}
                    value={getInput(scraper, inp.key)}
                    onChange={(e) => setInput(scraper.id, inp.key, e.target.value)}
                    disabled={isRunning(scraper.id)}
                  />
                </div>
              ))}
              <div className="flex gap-2 mt-2">
                <Button
                  className="flex-1"
                  size="sm"
                  disabled={isRunning(scraper.id)}
                  onClick={() => handleStart(scraper)}
                >
                  <Play className="h-4 w-4 mr-2" /> Start
                </Button>
                {isRunning(scraper.id) && (
                  <Button
                    className="flex-1"
                    size="sm"
                    variant="destructive"
                    onClick={() => handleStop(scraper)}
                  >
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" /> Stop
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Separator />

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Merge All Leads</CardTitle>
          <CardDescription>Combine all exported CSVs into master_leads.csv</CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            variant="secondary"
            disabled={isRunning("merge")}
            onClick={handleMerge}
          >
            {isRunning("merge") ? (
              <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Merging...</>
            ) : (
              <><Merge className="h-4 w-4 mr-2" /> Run Merge</>
            )}
          </Button>
        </CardContent>
      </Card>

      {status && status.tasks.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Task History</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1">
              {[...status.tasks].reverse().slice(0, 10).map((t) => (
                <div key={t.task_id} className="flex items-center justify-between text-xs py-1.5 border-b border-border last:border-0">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0">{t.source}</Badge>
                    <span className="text-muted-foreground">{t.task_id}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant={t.status === "completed" ? "default" : t.status === "failed" ? "destructive" : "secondary"} className="text-[10px] px-1.5 py-0">{t.status}</Badge>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
