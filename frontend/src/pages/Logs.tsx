import { useEffect, useState, useRef, useCallback } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { getLogs, type LogEntry, type LogsResponse } from "@/lib/api";
import { SOURCE_COLORS } from "@/lib/types";
import { PageLoading } from "@/components/shared/LoadingState";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
import { RefreshCw, Pause, Play, ChevronDown } from "lucide-react";

const SOURCE_FILTERS = [
  { id: "", label: "All" },
  { id: "api", label: "API" },
  { id: "clutch", label: "Clutch" },
  { id: "goodfirms", label: "GoodFirms" },
  { id: "maps", label: "Maps" },
  { id: "linkedin", label: "LinkedIn" },
  { id: "merge", label: "Merge" },
];

const LEVEL_COLORS: Record<string, string> = {
  ERROR: "bg-red-500/15 text-red-400 border-red-500/30",
  WARNING: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
  INFO: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  DEBUG: "bg-gray-500/15 text-gray-400 border-gray-500/30",
};

function levelBadgeClass(level: string | null): string {
  return LEVEL_COLORS[level ?? ""] || "bg-gray-500/15 text-gray-400 border-gray-500/30";
}

function sourceBadgeClass(name: string | null): string {
  return SOURCE_COLORS[name ?? ""] || "bg-gray-500/10 text-gray-400 border-gray-500/30";
}

function LogLine({ entry }: { entry: LogEntry }) {
  return (
    <div className="flex items-start gap-2 px-3 py-1 hover:bg-white/[0.03] border-b border-white/5 transition-colors">
      <span className="text-[11px] text-white/20 shrink-0 w-10 text-right font-mono tabular-nums">
        {entry.lineno}
      </span>
      {entry.timestamp && (
        <span className="text-[11px] text-white/30 shrink-0 w-[150px] font-mono tabular-nums">
          {entry.timestamp}
        </span>
      )}
      {entry.level && (
        <Badge
          variant="outline"
          className={`${levelBadgeClass(entry.level)} text-[10px] px-1.5 py-0 h-4 shrink-0 font-mono`}
        >
          {entry.level}
        </Badge>
      )}
      {entry.name && (
        <Badge
          variant="outline"
          className={`${sourceBadgeClass(entry.name)} text-[10px] px-1.5 py-0 h-4 shrink-0 font-mono`}
        >
          {entry.name}
        </Badge>
      )}
      <span
        className={`text-[12px] font-mono leading-5 whitespace-pre-wrap break-all ${
          entry.level === "ERROR"
            ? "text-red-300"
            : entry.level === "WARNING"
              ? "text-yellow-300"
              : "text-green-300/90"
        }`}
      >
        {entry.message}
      </span>
    </div>
  );
}

export default function Logs() {
  const [data, setData] = useState<LogsResponse | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState("");
  const [lines, setLines] = useState(200);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [autoScroll, setAutoScroll] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const prevLengthRef = useRef(0);
  const initialLoadDone = useRef(false);
  const linesRef = useRef(lines);

  const load = useCallback(() => {
    const isInitial = !initialLoadDone.current;
    if (isInitial) setInitialLoading(true);
    setRefreshing(true);
    if (!isInitial) setError(null);
    getLogs({ lines: linesRef.current, reverse: true })
      .then((d) => { setData(d); setError(null); })
      .catch((err) => {
        if (isInitial) setError(err instanceof Error ? err.message : "Failed to load logs");
      })
      .finally(() => { setRefreshing(false); setInitialLoading(false); initialLoadDone.current = true; });
  }, []);

  useEffect(() => {
    linesRef.current = lines;
  }, [lines]);

  useEffect(() => {
    load();
    if (!autoRefresh) return;

    function tick() {
      if (document.hidden) return;
      load();
    }
    const i = setInterval(tick, 3000);
    return () => clearInterval(i);
  }, [load, autoRefresh]);

  useEffect(() => {
    if (!autoScroll || !containerRef.current || !data) return;
    if (data.entries.length > prevLengthRef.current) {
      containerRef.current.scrollTo({ top: containerRef.current.scrollHeight, behavior: "smooth" });
    }
    prevLengthRef.current = data.entries.length;
  }, [data, autoScroll]);

  const entries = (data?.entries || []).filter((e) => {
    if (!sourceFilter) return true;
    const needle = sourceFilter === "api" ? "api" : sourceFilter;
    return (
      (e.name && e.name.toLowerCase().includes(needle)) ||
      (e.message && e.message.toLowerCase().includes(needle))
    );
  });

  return (
    <div className="space-y-3 h-full flex flex-col">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-bold">Logs</h1>
          <p className="text-sm text-muted-foreground mt-1">system.log &mdash; real-time tail</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={lines}
            onChange={(e) => setLines(Number(e.target.value))}
            className="h-8 rounded-md border border-input bg-transparent px-2 text-xs"
          >
            <option value={100}>100 lines</option>
            <option value={200}>200 lines</option>
            <option value={500}>500 lines</option>
            <option value={1000}>1000 lines</option>
            <option value={5000}>5000 lines</option>
          </select>
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            onClick={() => setAutoRefresh(!autoRefresh)}
          >
            {autoRefresh ? (
              <><Pause className="h-3.5 w-3.5 mr-1" /> Pause</>
            ) : (
              <><Play className="h-3.5 w-3.5 mr-1" /> Live</>
            )}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            onClick={() => setAutoScroll(!autoScroll)}
          >
            <ChevronDown className={`h-3.5 w-3.5 mr-1 ${autoScroll ? "" : "opacity-50"}`} />
            Scroll
          </Button>
          <Button variant="outline" size="sm" className="h-8" onClick={load} disabled={refreshing}>
            <RefreshCw className={`h-3.5 w-3.5 mr-1 ${refreshing ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      <div className="flex items-center gap-1.5 flex-wrap">
        {SOURCE_FILTERS.map((sf) => (
          <Button
            key={sf.id}
            variant={sourceFilter === sf.id ? "default" : "outline"}
            size="sm"
            className="h-7 text-xs"
            onClick={() => setSourceFilter(sf.id)}
          >
            {sf.label}
          </Button>
        ))}
      </div>

      <Card
        ref={containerRef}
        className="flex-1 min-h-0 overflow-y-auto rounded-lg border-zinc-700/50 bg-zinc-950"
        style={{ scrollBehavior: "smooth" }}
      >
        {initialLoading ? (
          <div className="p-6"><PageLoading /></div>
        ) : error && !data ? (
          <div className="p-6"><ErrorState message={error} onRetry={load} /></div>
        ) : entries.length === 0 ? (
          <div className="p-6">
            <EmptyState
              title="No log entries"
              message={sourceFilter ? `No entries matching "${sourceFilter}"` : "Log file is empty"}
            />
          </div>
        ) : (
          <div className="py-2">
            <div className="flex items-center gap-2 px-3 py-1.5 border-b border-white/5 text-[10px] text-white/20 font-mono uppercase tracking-wider">
              <span className="w-10 shrink-0">Line</span>
              <span className="w-[150px] shrink-0">Timestamp</span>
              <span className="w-[68px] shrink-0">Level</span>
              <span className="w-[72px] shrink-0">Source</span>
              <span>Message</span>
            </div>
            {entries.map((entry) => (
              <LogLine key={`${entry.lineno}-${entry.timestamp ?? ""}`} entry={entry} />
            ))}
          </div>
        )}
      </Card>

      {data && (
        <div className="text-[11px] text-muted-foreground text-right">
          {data.returned} of {data.total_lines} lines
          {autoRefresh && " · auto-refreshing every 3s"}
        </div>
      )}
    </div>
  );
}
