import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { getSettings, updateSettings, getHealth, type HealthResponse, type SystemConfig } from "@/lib/api";
import { PageLoading } from "@/components/shared/LoadingState";
import { ErrorState } from "@/components/shared/ErrorState";
import { toast } from "@/hooks/use-toast";
import { Save, Server, Settings2, Download } from "lucide-react";

const API_BASE = import.meta.env.VITE_API_URL || "/api";

function InfoRow({ label, value, variant }: { label: string; value: string; variant?: "default" | "secondary" | "destructive" }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <Badge variant={variant || (value === "ok" || value === "active" ? "default" : "secondary")} className="text-xs">
        {value}
      </Badge>
    </div>
  );
}

function FieldRow({ label, id, children }: { label: string; id: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <label htmlFor={id} className="text-sm text-muted-foreground shrink-0">{label}</label>
      <div className="w-28 sm:w-36">{children}</div>
    </div>
  );
}

function validateConfig(cfg: SystemConfig): string[] {
  const errors: string[] = [];
  if (cfg.browser.timeout < 1000) errors.push("Timeout must be at least 1000ms");
  if (cfg.browser.retry_count < 0) errors.push("Retry count cannot be negative");
  if (cfg.browser.min_delay < 0) errors.push("Min delay cannot be negative");
  if (cfg.browser.max_delay <= cfg.browser.min_delay) errors.push("Max delay must be greater than min delay");
  if (cfg.browser.concurrency < 1) errors.push("Concurrency must be at least 1");
  if (!["csv", "json", "parquet", "xlsx"].includes(cfg.export.format)) errors.push("Export format must be csv, json, parquet, or xlsx");
  return errors;
}

export default function Settings() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [config, setConfig] = useState<SystemConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([getHealth(), getSettings()])
      .then(([h, c]) => { setHealth(h); setConfig(c); })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  function patch<K extends keyof SystemConfig>(section: K, key: string, value: unknown) {
    if (!config) return;
    setConfig({
      ...config,
      [section]: { ...config[section], [key]: value },
    });
  }

  async function handleSave() {
    if (!config) return;
    const errors = validateConfig(config);
    setValidationErrors(errors);
    if (errors.length > 0) {
      toast({ title: "Validation failed", description: errors.join(", "), variant: "destructive" });
      return;
    }
    setSaving(true);
    try {
      await updateSettings(config);
      setValidationErrors([]);
      toast({ title: "Settings saved", description: "Configuration updated successfully" });
      load();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Save failed";
      toast({ title: "Error", description: msg, variant: "destructive" });
    } finally {
      setSaving(false);
    }
  }

  if (loading && !config) return <PageLoading />;
  if (error) return <ErrorState message={error} onRetry={load} />;

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Settings</h1>
          <p className="text-sm text-muted-foreground mt-1">System configuration</p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <Server className="h-4 w-4" /> API Connection
          </CardTitle>
          <CardDescription>FastAPI backend server status</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">API URL</span>
            <code className="text-xs bg-muted px-2 py-0.5 rounded">{API_BASE}</code>
          </div>
          <Separator />
          <InfoRow label="Status" value={health ? "connected" : "disconnected"} variant={health ? "default" : "destructive"} />
          {health && (
            <>
              <Separator />
              <InfoRow label="Server Status" value={health.status} />
              <Separator />
              <InfoRow label="Browser Session" value={health.browser_session} />
              <Separator />
              <InfoRow label="Active Tasks" value={String(health.active_tasks)} />
            </>
          )}
        </CardContent>
      </Card>

      {config && (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <Settings2 className="h-4 w-4" /> Browser
              </CardTitle>
              <CardDescription>Playwright browser session configuration</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <FieldRow label="Headless mode" id="headless">
                <div className="flex items-center gap-2">
                  <input
                    id="headless"
                    type="checkbox"
                    checked={config.browser.headless}
                    onChange={(e) => patch("browser", "headless", e.target.checked)}
                    className="rounded border-input h-4 w-4 accent-primary"
                  />
                  <span className="text-xs text-muted-foreground">{config.browser.headless ? "On" : "Off"}</span>
                </div>
              </FieldRow>
              <Separator />
              <FieldRow label="Timeout (ms)" id="timeout">
                <Input
                  id="timeout"
                  type="number"
                  min={1000}
                  step={1000}
                  value={config.browser.timeout}
                  onChange={(e) => patch("browser", "timeout", parseInt(e.target.value) || 0)}
                />
              </FieldRow>
              <Separator />
              <FieldRow label="Retry count" id="retry_count">
                <Input
                  id="retry_count"
                  type="number"
                  min={0}
                  step={1}
                  value={config.browser.retry_count}
                  onChange={(e) => patch("browser", "retry_count", parseInt(e.target.value) || 0)}
                />
              </FieldRow>
              <Separator />
              <FieldRow label="Min delay (s)" id="min_delay">
                <Input
                  id="min_delay"
                  type="number"
                  min={0}
                  step={0.1}
                  value={config.browser.min_delay}
                  onChange={(e) => patch("browser", "min_delay", parseFloat(e.target.value) || 0)}
                />
              </FieldRow>
              <Separator />
              <FieldRow label="Max delay (s)" id="max_delay">
                <Input
                  id="max_delay"
                  type="number"
                  min={0}
                  step={0.1}
                  value={config.browser.max_delay}
                  onChange={(e) => patch("browser", "max_delay", parseFloat(e.target.value) || 0)}
                />
              </FieldRow>
              <Separator />
              <FieldRow label="Concurrency" id="concurrency">
                <Input
                  id="concurrency"
                  type="number"
                  min={1}
                  step={1}
                  value={config.browser.concurrency}
                  onChange={(e) => patch("browser", "concurrency", parseInt(e.target.value) || 1)}
                />
              </FieldRow>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <Download className="h-4 w-4" /> Export
              </CardTitle>
              <CardDescription>Lead export format and encoding</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <FieldRow label="Format" id="export_format">
                <select
                  id="export_format"
                  value={config.export.format}
                  onChange={(e) => patch("export", "format", e.target.value)}
                  className="w-full h-9 rounded-md border border-input bg-transparent px-3 text-sm"
                >
                  <option value="csv">CSV</option>
                  <option value="json">JSON</option>
                  <option value="parquet">Parquet</option>
                  <option value="xlsx">XLSX</option>
                </select>
              </FieldRow>
            </CardContent>
          </Card>

          {validationErrors.length > 0 && (
            <Card className="border-destructive/50 bg-destructive/5">
              <CardContent className="py-3">
                <ul className="text-xs text-destructive space-y-0.5">
                  {validationErrors.map((e, i) => <li key={i}>{e}</li>)}
                </ul>
              </CardContent>
            </Card>
          )}

          <div className="flex justify-end">
            <Button onClick={handleSave} disabled={saving} size="lg">
              <Save className={`h-4 w-4 mr-2 ${saving ? "animate-pulse" : ""}`} />
              {saving ? "Saving..." : "Save Settings"}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
