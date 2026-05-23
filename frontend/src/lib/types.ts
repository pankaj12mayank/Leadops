export interface ScraperDef {
  id: string;
  label: string;
  description: string;
  docsUrl?: string;
  inputs: ScraperInput[];
}

export interface ScraperInput {
  key: string;
  label: string;
  type: "text" | "number";
  defaultValue: string;
}

export const SCRAPERS: ScraperDef[] = [
  {
    id: "clutch",
    label: "Clutch.co",
    description: "Extract company leads from Clutch.co search results",
    inputs: [
      { key: "query", label: "Search query", type: "text", defaultValue: "" },
      { key: "max_pages", label: "Max pages", type: "number", defaultValue: "5" },
    ],
  },
  {
    id: "goodfirms",
    label: "GoodFirms.co",
    description: "Extract company leads from GoodFirms.co search results",
    inputs: [
      { key: "query", label: "Search query", type: "text", defaultValue: "" },
      { key: "max_pages", label: "Max pages", type: "number", defaultValue: "5" },
    ],
  },
  {
    id: "maps",
    label: "Google Maps",
    description: "Extract business leads from Google Maps search results",
    inputs: [
      { key: "query", label: "Search query", type: "text", defaultValue: "" },
      { key: "max_cycles", label: "Max scroll cycles", type: "number", defaultValue: "30" },
    ],
  },
  {
    id: "linkedin",
    label: "LinkedIn Enrichment",
    description: "Enrich existing company leads with LinkedIn data",
    inputs: [
      { key: "csv_path", label: "CSV file path (leave empty for default)", type: "text", defaultValue: "" },
    ],
  },
];

export const SOURCE_COLORS: Record<string, string> = {
  clutch: "bg-blue-500/10 text-blue-400 border-blue-500/30",
  goodfirms: "bg-green-500/10 text-green-400 border-green-500/30",
  maps: "bg-orange-500/10 text-orange-400 border-orange-500/30",
  linkedin: "bg-sky-500/10 text-sky-400 border-sky-500/30",
  merge: "bg-purple-500/10 text-purple-400 border-purple-500/30",
};

export const TASK_STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-500/10 text-yellow-400 border-yellow-500/30",
  running: "bg-blue-500/10 text-blue-400 border-blue-500/30",
  completed: "bg-green-500/10 text-green-400 border-green-500/30",
  failed: "bg-red-500/10 text-red-400 border-red-500/30",
  cancelled: "bg-gray-500/10 text-gray-400 border-gray-500/30",
};
