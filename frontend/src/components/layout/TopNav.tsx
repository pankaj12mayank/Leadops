import { Menu, Activity } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { getHealth, type HealthResponse } from "@/lib/api";

interface TopNavProps {
  onMenuClick: () => void;
}

export function TopNav({ onMenuClick }: TopNavProps) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    function fetch() {
      getHealth()
        .then((h) => { if (mounted) setHealth(h); })
        .catch(() => { if (mounted) setHealth(null); })
        .finally(() => { if (mounted) setLoading(false); });
    }
    fetch();
    const interval = setInterval(fetch, 10000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-4 border-b border-border bg-background px-4 lg:px-6">
      <Button variant="ghost" size="icon" onClick={onMenuClick} className="lg:hidden">
        <Menu className="h-5 w-5" />
      </Button>
      <div className="flex-1" />
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Activity className={cn("h-3 w-3", health?.status === "ok" ? "text-green-400" : "text-red-400")} />
        <span>
          {loading ? "Connecting..." : health ? `API: ${health.status}` : "Disconnected"}
        </span>
        {health && (
          <>
            <span className="hidden sm:inline">·</span>
            <span className="hidden sm:inline">
              Browser: {health.browser_session === "active" ? "Active" : "Inactive"}
            </span>
            <span className="hidden sm:inline">·</span>
            <span className="hidden sm:inline">Tasks: {health.active_tasks}</span>
          </>
        )}
      </div>
    </header>
  );
}

