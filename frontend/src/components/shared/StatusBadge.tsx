import { cn } from "@/lib/utils";
import { SOURCE_COLORS, TASK_STATUS_COLORS } from "@/lib/types";

interface StatusBadgeProps {
  value: string;
  type?: "source" | "status";
}

export function StatusBadge({ value, type = "status" }: StatusBadgeProps) {
  const colors = type === "source" ? SOURCE_COLORS : TASK_STATUS_COLORS;
  const colorClass = colors[value] || "bg-gray-500/10 text-gray-400 border-gray-500/30";

  return (
    <span className={cn("inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium", colorClass)}>
      {value}
    </span>
  );
}
