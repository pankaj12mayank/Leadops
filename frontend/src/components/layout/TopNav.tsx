import { Menu, Activity, Sun, Moon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { getHealth, type HealthResponse } from "@/lib/api";

interface TopNavProps {
  onMenuClick: () => void;
}

function useTheme() {
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    const stored = localStorage.getItem("theme");
    if (stored === "light" || stored === "dark") return stored;
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  });

  useEffect(() => {
    document.documentElement.classList.toggle("light", theme === "light");
    localStorage.setItem("theme", theme);
  }, [theme]);

  const toggle = () => setTheme((t) => (t === "dark" ? "light" : "dark"));
  return { theme, toggle };
}

export function TopNav({ onMenuClick }: TopNavProps) {
  const { theme, toggle } = useTheme();
  const { t } = useTranslation();
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
      <Button variant="ghost" size="icon" onClick={onMenuClick} className="lg:hidden" aria-label={t("nav.open_menu")}>
        <Menu className="h-5 w-5" />
      </Button>
      <div className="flex-1" />
      <Button variant="ghost" size="icon" onClick={toggle} aria-label={theme === "dark" ? t("nav.theme_light") : t("nav.theme_dark")}>
        {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </Button>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Activity className={cn("h-3 w-3", health?.status === "ok" ? "text-green-400" : "text-red-400")} />
        <span>
          {loading ? t("app.connecting") : health ? `${t("app.api")}: ${health.status}` : t("app.disconnected")}
        </span>
        {health && (
          <>
            <span className="hidden sm:inline">·</span>
            <span className="hidden sm:inline">
              {t("app.browser")}: {health.browser_session === "active" ? t("app.active") : t("app.inactive")}
            </span>
            <span className="hidden sm:inline">·</span>
            <span className="hidden sm:inline">{t("app.tasks")}: {health.active_tasks}</span>
          </>
        )}
      </div>
    </header>
  );
}

