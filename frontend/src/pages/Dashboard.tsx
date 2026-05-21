import { useEffect, useState, useCallback, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getHealth, getExports, getStatus, type HealthResponse, type ExportsResponse, type StatusResponse } from "@/lib/api";
import { PageLoading } from "@/components/shared/LoadingState";
import { ErrorState } from "@/components/shared/ErrorState";
import { Activity, Globe, FileDown, ListChecks, Wifi, WifiOff } from "lucide-react";

export default function Dashboard() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [exports, setExports] = useState<ExportsResponse | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const initialLoadDone = useRef(false);

  const load = useCallback(() => {
    setError(null);
    if (!initialLoadDone.current) {
      setInitialLoading(true);
    }
    setLoading(true);
    Promise.all([getHealth(), getExports(), getStatus()])
      .then(([h, e, s]) => { setHealth(h); setExports(e); setStatus(s); })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load dashboard"))
      .finally(() => { setLoading(false); setInitialLoading(false); initialLoadDone.current = true; });
  }, []);

  useEffect(() => { load(); const i = setInterval(load, 15000); return () => clearInterval(i); }, [load]);

  if (initialLoading) return <PageLoading />;
  if (error && !health) return <ErrorState message={error} onRetry={load} />;

  const activeCount = status?.active_sources?.length || 0;
  const recentTasks = (status?.tasks || []).slice(-5).reverse();
  const exportFiles = exports?.files || [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="text-sm text-muted-foreground mt-1">Lead Extraction System overview</p>
      </div>

      <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard icon={Wifi} label="API Status" value={health?.status || "down"} color={health?.status === "ok" ? "text-green-400" : "text-red-400"} />
        <StatCard icon={Globe} label="Browser" value={health?.browser_session === "active" ? "Active" : "Inactive"} color={health?.browser_session === "active" ? "text-green-400" : "text-yellow-400"} />
        <StatCard icon={ListChecks} label="Active Tasks" value={String(activeCount)} color="text-blue-400" />
        <StatCard icon={FileDown} label="Export Files" value={String(exportFiles.length)} color="text-purple-400" />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Recent Tasks</CardTitle>
          </CardHeader>
          <CardContent>
            {recentTasks.length === 0 ? (
              <p className="text-sm text-muted-foreground py-8 text-center">No tasks executed yet</p>
            ) : (
              <div className="space-y-2">
                {recentTasks.map((t) => (
                  <div key={t.task_id} className="flex items-center justify-between text-sm py-1.5 border-b border-border last:border-0">
                    <div className="flex items-center gap-2">
                      <StatusBadge value={t.source} type="source" />
                      <span className="text-muted-foreground text-xs">{t.task_id}</span>
                    </div>
                    <StatusBadge value={t.status} />
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Recent Exports</CardTitle>
          </CardHeader>
          <CardContent>
            {exportFiles.length === 0 ? (
              <p className="text-sm text-muted-foreground py-8 text-center">No export files yet</p>
            ) : (
              <div className="space-y-2">
                {exportFiles.slice(0, 8).map((f, i) => (
                  <div key={i} className="flex items-center justify-between text-sm py-1.5 border-b border-border last:border-0">
                    <div className="flex items-center gap-2 min-w-0">
                      <StatusBadge value={f.source} type="source" />
                      <span className="truncate text-xs">{f.filename}</span>
                    </div>
                    <span className="text-xs text-muted-foreground shrink-0 ml-2">
                      {(f.size_bytes / 1024).toFixed(1)} KB
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, color }: { icon: React.ElementType; label: string; value: string; color: string }) {
  return (
    <Card>
      <CardContent className="p-4 flex items-center gap-3">
        <Icon className={`h-8 w-8 ${color}`} />
        <div>
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="text-lg font-bold">{value}</p>
        </div>
      </CardContent>
    </Card>
  );
}

function StatusBadge({ value, type = "status" }: { value: string; type?: "source" | "status" }) {
  const colors: Record<string, string> = type === "source"
    ? { clutch: "bg-blue-500/10 text-blue-400", goodfirms: "bg-green-500/10 text-green-400", maps: "bg-orange-500/10 text-orange-400", linkedin: "bg-sky-500/10 text-sky-400", merge: "bg-purple-500/10 text-purple-400" }
    : { pending: "bg-yellow-500/10 text-yellow-400", running: "bg-blue-500/10 text-blue-400", completed: "bg-green-500/10 text-green-400", failed: "bg-red-500/10 text-red-400", cancelled: "bg-gray-500/10 text-gray-400" };
  return <span className={`inline-flex items-center rounded-md border border-current/30 px-2 py-0.5 text-xs font-medium ${colors[value] || "bg-gray-500/10 text-gray-400"}`}>{value}</span>;
}
