import { useEffect, useState, useCallback, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getExports, deleteExport, getExportDownloadUrl, type ExportFile } from "@/lib/api";
import { SOURCE_COLORS } from "@/lib/types";
import { PageLoading } from "@/components/shared/LoadingState";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
import { Download, Trash2, RefreshCw, FileText, HardDrive, Calendar, Filter } from "lucide-react";
import { toast } from "@/hooks/use-toast";

const SOURCE_OPTIONS = ["", "clutch", "goodfirms", "maps", "linkedin", "merged"] as const;
const TYPE_OPTIONS = ["", "raw", "merged"] as const;

const SOURCE_LABELS: Record<string, string> = {
  clutch: "Clutch.co",
  goodfirms: "GoodFirms.co",
  maps: "Google Maps",
  linkedin: "LinkedIn Enrichment",
  merged: "Merged",
};

function countBy<T>(items: T[], key: (item: T) => string): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const item of items) {
    const k = key(item);
    counts[k] = (counts[k] || 0) + 1;
  }
  return counts;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(2)} MB`;
}

export default function Exports() {
  const [data, setData] = useState<ExportFile[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [deleting, setDeleting] = useState<Set<string>>(new Set());

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getExports()
      .then((r) => setData(r.files))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load exports"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const todayStr = useMemo(() => new Date().toISOString().slice(0, 10), []);

  const filtered = (data || []).filter((f) => {
    if (sourceFilter && f.source !== sourceFilter) return false;
    if (typeFilter && f.type !== typeFilter) return false;
    if (dateFrom || dateTo) {
      const d = new Date(f.last_modified);
      const ds = d.toISOString().slice(0, 10);
      if (dateFrom && ds < dateFrom) return false;
      if (dateTo && ds > dateTo) return false;
    }
    return true;
  });

  async function handleDelete(file: ExportFile) {
    if (!confirm(`Delete "${file.filename}"? This cannot be undone.`)) return;
    setDeleting((prev) => new Set(prev).add(file.path));
    try {
      await deleteExport(file.path);
      toast({ title: "Deleted", description: file.filename });
      load();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Delete failed";
      toast({ title: "Error", description: msg, variant: "destructive" });
    } finally {
      setDeleting((prev) => { const s = new Set(prev); s.delete(file.path); return s; });
    }
  }

  const sourceCounts = data ? countBy(data, (f) => f.source) : {};
  const typeCounts = data ? countBy(data, (f) => f.type) : {};
  const totalSize = data ? data.reduce((s, f) => s + f.size_bytes, 0) : 0;

  if (loading && !data) return <PageLoading />;
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!data || data.length === 0) return <EmptyState title="No exports" message="Run scrapers and merge to generate export files." />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-bold">Exports</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {data.length} files &middot; {formatSize(totalSize)} total
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`h-4 w-4 mr-1 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Filter className="h-4 w-4" /> Filters
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-muted-foreground">Source</label>
              <select
                value={sourceFilter}
                onChange={(e) => setSourceFilter(e.target.value)}
                className="h-8 rounded-md border border-input bg-transparent px-2 text-xs"
              >
                <option value="">All ({data.length})</option>
                {SOURCE_OPTIONS.filter(Boolean).map((s) => (
                  <option key={s} value={s}>
                    {SOURCE_LABELS[s] || s} ({sourceCounts[s] || 0})
                  </option>
                ))}
              </select>
            </div>

            <div className="flex items-center gap-1.5">
              <label className="text-xs text-muted-foreground">Type</label>
              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                className="h-8 rounded-md border border-input bg-transparent px-2 text-xs"
              >
                <option value="">All ({data.length})</option>
                {TYPE_OPTIONS.filter(Boolean).map((t) => (
                  <option key={t} value={t}>
                    {t.charAt(0).toUpperCase() + t.slice(1)} ({typeCounts[t] || 0})
                  </option>
                ))}
              </select>
            </div>

            <div className="flex items-center gap-1.5">
              <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
              <Input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                max={dateTo || todayStr}
                className="h-8 w-36 text-xs"
                placeholder="From"
              />
              <span className="text-xs text-muted-foreground">&ndash;</span>
              <Input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                min={dateFrom || undefined}
                max={todayStr}
                className="h-8 w-36 text-xs"
                placeholder="To"
              />
            </div>

            {(sourceFilter || typeFilter || dateFrom || dateTo) && (
              <Button
                variant="ghost"
                size="sm"
                className="h-8 text-xs"
                onClick={() => { setSourceFilter(""); setTypeFilter(""); setDateFrom(""); setDateTo(""); }}
              >
                Clear filters
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[100px]">Source</TableHead>
                <TableHead>Filename</TableHead>
                <TableHead className="w-[70px]">Type</TableHead>
                <TableHead className="w-[80px] text-right">Size</TableHead>
                <TableHead className="w-[140px] hidden sm:table-cell">Modified</TableHead>
                <TableHead className="w-[80px] text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                    No exports match the current filters
                  </TableCell>
                </TableRow>
              ) : (
                filtered.map((file) => (
                  <TableRow key={file.path}>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className={`${SOURCE_COLORS[file.source] || ""} text-[10px] px-1.5 py-0 font-mono`}
                      >
                        {file.source}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs max-w-[200px] sm:max-w-none truncate">
                      <span className="flex items-center gap-1.5">
                        <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        {file.filename}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className={`text-[10px] px-1.5 py-0 font-mono ${
                          file.type === "merged"
                            ? "bg-purple-500/10 text-purple-400 border-purple-500/30"
                            : "bg-blue-500/10 text-blue-400 border-blue-500/30"
                        }`}
                      >
                        {file.type}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      <span className="flex items-center justify-end gap-1">
                        <HardDrive className="h-3 w-3 text-muted-foreground" />
                        {formatSize(file.size_bytes)}
                      </span>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground hidden sm:table-cell tabular-nums">
                      <span title={formatDateTime(file.last_modified)}>
                        {formatDate(file.last_modified)}
                      </span>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        <a href={getExportDownloadUrl(file)} download>
                          <Button variant="ghost" size="icon" className="h-7 w-7">
                            <Download className="h-3.5 w-3.5" />
                          </Button>
                        </a>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-red-400 hover:text-red-300 hover:bg-red-500/10"
                          disabled={deleting.has(file.path)}
                          onClick={() => handleDelete(file)}
                        >
                          {deleting.has(file.path) ? (
                            <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Trash2 className="h-3.5 w-3.5" />
                          )}
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {filtered.length < data.length && (
        <p className="text-xs text-muted-foreground text-right">
          Showing {filtered.length} of {data.length} files
        </p>
      )}
    </div>
  );
}
