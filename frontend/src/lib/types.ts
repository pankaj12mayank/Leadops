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

export const PREVIEW_COLUMNS = ["business_name", "website", "phone", "location", "rating"] as const;
