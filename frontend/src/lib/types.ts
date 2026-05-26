export const SOURCES = [
  { id: "clutch", label: "Clutch.co" },
  { id: "goodfirms", label: "GoodFirms.co" },
  { id: "maps", label: "Google Maps" },
  { id: "linkedin", label: "LinkedIn Enrichment" },
] as const;

export const SOURCE_COLORS: Record<string, string> = {
  clutch: "bg-blue-500/10 text-blue-400 border-blue-500/30",
  goodfirms: "bg-green-500/10 text-green-400 border-green-500/30",
  maps: "bg-orange-500/10 text-orange-400 border-orange-500/30",
  linkedin: "bg-sky-500/10 text-sky-400 border-sky-500/30",
};

export const JOB_STATUS_COLORS: Record<string, string> = {
  queued: "bg-yellow-500/10 text-yellow-400 border-yellow-500/30",
  running: "bg-blue-500/10 text-blue-400 border-blue-500/30",
  completed: "bg-green-500/10 text-green-400 border-green-500/30",
  failed: "bg-red-500/10 text-red-400 border-red-500/30",
  cancelled: "bg-gray-500/10 text-gray-400 border-gray-500/30",
};

export const PREVIEW_COLUMNS = ["business_name", "website", "phone", "location", "rating"] as const;
