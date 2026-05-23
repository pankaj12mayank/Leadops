import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import {
  LayoutDashboard,
  Search,
  FileText,
  Download,
  Settings,
  X,
} from "lucide-react";

const NAV_ITEMS = [
  { to: "/", labelKey: "nav.dashboard", icon: LayoutDashboard },
  { to: "/scrapers", labelKey: "nav.scrapers", icon: Search },
  { to: "/logs", labelKey: "nav.logs", icon: FileText },
  { to: "/exports", labelKey: "nav.exports", icon: Download },
  { to: "/settings", labelKey: "nav.settings", icon: Settings },
];

interface SidebarProps {
  open: boolean;
  onClose: () => void;
}

export function Sidebar({ open, onClose }: SidebarProps) {
  const { t } = useTranslation();
  return (
    <>
      {open && (
        <div className="fixed inset-0 z-40 bg-black/50 lg:hidden" onClick={onClose} role="dialog" aria-modal="true" aria-label={t("nav.sidebar_label")} />
      )}
      <aside
        className={cn(
          "fixed top-0 left-0 z-50 h-full w-64 border-r border-border bg-sidebar transition-transform duration-200 lg:static lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <div className="flex h-14 items-center justify-between px-4 border-b border-border">
          <span className="font-semibold text-sm">{t("app.title")}</span>
          <button onClick={onClose} className="lg:hidden p-1 rounded-md hover:bg-sidebar-muted" aria-label={t("nav.close_sidebar")}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <nav className="p-2 space-y-1">
          {NAV_ITEMS.map(({ to, labelKey, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              onClick={onClose}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors",
                  isActive
                    ? "bg-sidebar-muted text-sidebar-foreground font-medium"
                    : "text-muted-foreground hover:bg-sidebar-muted hover:text-sidebar-foreground"
                )
              }
            >
              <Icon className="h-4 w-4" />
              {t(labelKey)}
            </NavLink>
          ))}
        </nav>
      </aside>
    </>
  );
}
