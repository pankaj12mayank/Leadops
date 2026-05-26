import { vi, afterEach } from "vitest";
import "@testing-library/jest-dom";

vi.mock("@/lib/api", () => ({
  getHealth: vi.fn().mockResolvedValue({ status: "ok", browser_session: "active", current_job_id: null }),
  getStatus: vi.fn().mockResolvedValue({ current_job: null, total_jobs: 0, jobs: [] }),
  startScraper: vi.fn().mockResolvedValue({ job_id: 1, status: "queued" }),
  getJob: vi.fn().mockResolvedValue({ job: { id: 1, source: "clutch", status: "completed", total_found: 10 } }),
  getJobLeads: vi.fn().mockResolvedValue({ leads: [], total: 0 }),
  getJobExportUrl: vi.fn().mockReturnValue("/download/job/1"),
  getPreviewStatus: vi.fn().mockResolvedValue({ previewed: false, viewed_at: null }),
  unlockPreview: vi.fn().mockResolvedValue({ granted: true }),
}));

afterEach(() => {
  vi.clearAllMocks();
});
