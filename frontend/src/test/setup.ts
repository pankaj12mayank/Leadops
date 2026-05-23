import { vi, afterEach } from "vitest";
import "@testing-library/jest-dom";

vi.mock("@/lib/api", () => ({
  getHealth: vi.fn().mockResolvedValue({ status: "ok", browser_session: "active", active_tasks: 0 }),
  getStatus: vi.fn().mockResolvedValue({ active_sources: [], total_tasks: 0, tasks: [] }),
  getExports: vi.fn().mockResolvedValue({ total_files: 0, total_size_bytes: 0, total_size_kb: 0, sources: [], files: [] }),
  getSettings: vi.fn().mockResolvedValue({
    browser: { headless: true, timeout: 30000, retry_count: 3, min_delay: 1, max_delay: 3, concurrency: 1, viewport_width: 1920, viewport_height: 1080, user_agent: "", locale: "en-US", timezone_id: "America/New_York", geolocation: { latitude: 40.7, longitude: -74.0 } },
    session: { storage_path: "sessions", state_file: "auth_state.json", auto_save: true },
    export: { format: "csv", encoding: "utf-8-sig" },
    logging: { level: "INFO", file: "logs/system.log", max_bytes: 10485760, backup_count: 5, format: "" },
    paths: { exports: "exports", screenshots: "screenshots", temp: "temp", sessions: "sessions" },
  }),
  getLogs: vi.fn().mockResolvedValue({ file: "logs/system.log", total_lines: 0, returned: 0, entries: [] }),
  startScraper: vi.fn().mockResolvedValue({ task_id: "test", source: "test", status: "started" }),
  stopScraper: vi.fn().mockResolvedValue({ source: "test", status: "cancelled" }),
  runMerge: vi.fn().mockResolvedValue({ task_id: "merge", source: "merge", status: "started" }),
  deleteExport: vi.fn().mockResolvedValue({ deleted: true, path: "test.csv" }),
  updateSettings: vi.fn().mockResolvedValue({}),
  getExportDownloadUrl: vi.fn().mockReturnValue("/download/test.csv"),
}));

afterEach(() => {
  vi.clearAllMocks();
});
