import axios from "axios";

const API_BASE = import.meta.env.VITE_API_URL || "/api";

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 10000,
  headers: { "Content-Type": "application/json" },
});

export interface HealthResponse {
  status: string;
  browser_session: string;
  active_tasks: number;
}

export interface TaskInfo {
  task_id: string;
  source: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  result: boolean | null;
  error: string | null;
}

export interface StatusResponse {
  active_sources: string[];
  total_tasks: number;
  tasks: TaskInfo[];
}

export interface ExportFile {
  path: string;
  filename: string;
  size_bytes: number;
  source: string;
  last_modified: string;
  type: string;
}

export interface ExportsResponse {
  total_files: number;
  total_size_bytes: number;
  total_size_kb: number;
  sources: string[];
  files: ExportFile[];
}

export interface LogEntry {
  lineno: number;
  timestamp: string | null;
  level: string | null;
  name: string | null;
  message: string;
  raw: string;
}

export interface LogsResponse {
  file: string;
  total_lines: number;
  returned: number;
  entries: LogEntry[];
}

export interface LogsQuery {
  lines?: number;
  source?: string;
  reverse?: boolean;
}

export interface StartResponse {
  task_id: string;
  source: string;
  status: string;
}

export function getHealth(): Promise<HealthResponse> {
  return api.get("/health").then((r) => r.data);
}

export function getStatus(taskId?: string): Promise<StatusResponse> {
  const params = taskId ? { task_id: taskId } : {};
  return api.get("/status", { params }).then((r) => r.data);
}

export function startScraper(
  source: string,
  body: Record<string, unknown>
): Promise<StartResponse> {
  return api.post(`/start/${source}`, body).then((r) => r.data);
}

export function stopScraper(source: string): Promise<{ source: string; status: string }> {
  return api.post(`/stop/${source}`).then((r) => r.data);
}

export function runMerge(): Promise<StartResponse> {
  return api.post("/merge").then((r) => r.data);
}

export function getLogs(params?: LogsQuery): Promise<LogsResponse> {
  return api.get("/logs", { params }).then((r) => r.data);
}

export function getExports(): Promise<ExportsResponse> {
  return api.get("/exports").then((r) => r.data);
}

export function deleteExport(filePath: string): Promise<{ deleted: boolean; path: string }> {
  return api.delete(`/export/${encodeURI(filePath)}`).then((r) => r.data);
}

export function getExportDownloadUrl(file: ExportFile): string {
  return `${API_BASE}/download/${encodeURI(file.path)}`;
}

export interface GeoLocation {
  latitude: number;
  longitude: number;
}

export interface BrowserSettings {
  headless: boolean;
  timeout: number;
  retry_count: number;
  min_delay: number;
  max_delay: number;
  concurrency: number;
  viewport_width: number;
  viewport_height: number;
  user_agent: string;
  locale: string;
  timezone_id: string;
  geolocation: GeoLocation;
}

export interface SessionSettingsConfig {
  storage_path: string;
  state_file: string;
  auto_save: boolean;
}

export interface ExportSettingsConfig {
  format: string;
  encoding: string;
}

export interface LoggingSettingsConfig {
  level: string;
  file: string;
  max_bytes: number;
  backup_count: number;
  format: string;
}

export interface PathsConfig {
  exports: string;
  screenshots: string;
  temp: string;
  sessions: string;
}

export interface SystemConfig {
  browser: BrowserSettings;
  session: SessionSettingsConfig;
  export: ExportSettingsConfig;
  logging: LoggingSettingsConfig;
  paths: PathsConfig;
}

export function getSettings(): Promise<SystemConfig> {
  return api.get("/settings").then((r) => r.data);
}

export function updateSettings(body: SystemConfig): Promise<SystemConfig> {
  return api.post("/settings", body).then((r) => r.data);
}
