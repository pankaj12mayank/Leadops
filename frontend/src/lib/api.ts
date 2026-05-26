import axios from "axios";

export type { SiteContent } from "./site-content";

const API_BASE = import.meta.env.VITE_API_URL || "/api";

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 15000,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.response.use(
  (res) => {
    if (res.data && typeof res.data === "object" && "success" in res.data) {
      return { ...res, data: res.data.data ?? res.data };
    }
    return res;
  }
);

export interface HealthResp {
  status: string;
  browser_session: string;
  current_job_id: number | null;
}

export interface JobInfo {
  id: number;
  source: string;
  query: string | null;
  status: string;
  total_found: number;
  progress: number;
  created_at: string;
  updated_at: string;
  error_message: string | null;
}

export interface JobListResp {
  current_job: JobInfo | null;
  total_jobs: number;
  jobs: JobInfo[];
}

export interface LeadRow {
  id: number;
  source: string;
  business_name: string | null;
  website: string | null;
  phone: string | null;
  email: string | null;
  location: string | null;
  category: string | null;
  rating: number | null;
}

export interface JobLeadsResp {
  leads: LeadRow[];
  total: number;
}

export function getHealth(): Promise<HealthResp> {
  return api.get("/health").then((r) => r.data);
}

export function startScraper(source: string, body: Record<string, unknown>): Promise<{ job_id: number; status: string }> {
  return api.post(`/start/${source}`, body).then((r) => r.data);
}

export function getStatus(): Promise<JobListResp> {
  return api.get("/status").then((r) => r.data);
}

export function getJob(jobId: number): Promise<{ job: JobInfo }> {
  return api.get(`/db/jobs/${jobId}`).then((r) => r.data);
}

export function getJobLeads(jobId: number): Promise<JobLeadsResp> {
  return api.get(`/db/jobs/${jobId}/leads`).then((r) => r.data);
}

export function getJobExportUrl(jobId: number): string {
  return `${API_BASE}/download/job/${jobId}`;
}

export interface PreviewStatusResp {
  previewed: boolean;
  viewed_at: string | null;
}

export function getPreviewStatus(jobId: number): Promise<PreviewStatusResp> {
  return api.get(`/preview/status/${jobId}`).then((r) => r.data);
}

export function unlockPreview(jobId: number): Promise<{ granted: boolean; reason?: string }> {
  return api.post(`/preview/job/${jobId}`).then((r) => r.data);
}

export interface PaymentStatusResp {
  paid: boolean;
  exists: boolean;
  payment_status: string | null;
}

export function getPaymentStatus(jobId: number): Promise<PaymentStatusResp> {
  return api.get(`/stripe/check/${jobId}`).then((r) => r.data);
}

export function createCheckoutSession(jobId: number, successUrl?: string, cancelUrl?: string): Promise<{ checkout_url: string }> {
  return api.post("/stripe/checkout", { job_id: jobId, success_url: successUrl, cancel_url: cancelUrl }).then((r) => r.data);
}

// ── Admin API ──────────────────────────────────────────

export interface AdminLoginResp {
  token: string;
  email: string;
}

export interface AdminJobInfo {
  id: number;
  source: string;
  query: string | null;
  status: string;
  total_found: number;
  progress: number;
  created_at: string;
  updated_at: string;
  error_message: string | null;
  payment_status: string | null;
}

export interface AdminJobsResp {
  jobs: AdminJobInfo[];
  total: number;
}

export interface AdminRetryResp {
  new_job_id: number;
  source: string;
  query: string | null;
}

let _adminToken: string | null = null;

export function setAdminToken(token: string | null) {
  _adminToken = token;
  if (token) {
    sessionStorage.setItem("leadops_admin_token", token);
  } else {
    sessionStorage.removeItem("leadops_admin_token");
  }
}

export function getAdminToken(): string | null {
  if (!_adminToken) {
    _adminToken = sessionStorage.getItem("leadops_admin_token");
  }
  return _adminToken;
}

function adminApi() {
  const token = getAdminToken();
  return {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  };
}

export function adminLogin(email: string, password: string): Promise<AdminLoginResp> {
  return api.post("/admin/login", { email, password }).then((r) => r.data);
}

export function adminChangePassword(oldPassword: string, newPassword: string): Promise<{ changed: boolean }> {
  return api.post("/admin/change-password", { old_password: oldPassword, new_password: newPassword }, adminApi()).then((r) => r.data);
}

export function adminListJobs(): Promise<AdminJobsResp> {
  return api.get("/admin/jobs", adminApi()).then((r) => r.data);
}

export function adminRetryJob(jobId: number): Promise<AdminRetryResp> {
  return api.post(`/admin/jobs/${jobId}/retry`, {}, adminApi()).then((r) => r.data);
}

export function adminDeleteExport(jobId: number): Promise<{ deleted: boolean; job_id: number }> {
  return api.delete(`/admin/exports/${jobId}`, adminApi()).then((r) => r.data);
}
