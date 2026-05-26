import { useEffect, useState } from "react";
import { adminChangePassword, adminDeleteExport, adminListJobs, adminLogin, adminRetryJob, getAdminToken, setAdminToken, type AdminJobInfo } from "@/lib/api";
import { toast } from "@/hooks/use-toast";
import { Lock, RefreshCw, Trash2, LogOut, AlertCircle } from "lucide-react";

interface AdminSectionProps {
  strings?: Record<string, string>;
}

export default function AdminSection({ strings = {} }: AdminSectionProps) {
  const [token, setToken] = useState<string | null>(getAdminToken());
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);
  const [jobs, setJobs] = useState<AdminJobInfo[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [showPasswordForm, setShowPasswordForm] = useState(false);
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");

  const s = { loginTitle: "Admin Login", emailLabel: "Email", passwordLabel: "Password", loginCta: "Sign In", dashboardTitle: "Admin Dashboard", retryCta: "Retry", deleteCta: "Delete", loading: "Loading...", noJobs: "No jobs found", ...strings };

  useEffect(() => {
    if (token) fetchJobs();
  }, [token]);

  const fetchJobs = async () => {
    setLoadingJobs(true);
    try {
      const res = await adminListJobs();
      setJobs(res.jobs || []);
    } catch {
      setToken(null);
      setAdminToken(null);
      toast({ title: "Session expired", description: "Please log in again", variant: "destructive" });
    } finally {
      setLoadingJobs(false);
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoggingIn(true);
    try {
      const res = await adminLogin(email, password);
      setAdminToken(res.token);
      setToken(res.token);
      toast({ title: "Logged in", description: `Welcome ${res.email}` });
    } catch {
      toast({ title: "Login failed", description: "Invalid email or password", variant: "destructive" });
    } finally {
      setLoggingIn(false);
    }
  };

  const handleLogout = () => {
    setAdminToken(null);
    setToken(null);
    setJobs([]);
  };

  const handleRetry = async (jobId: number) => {
    try {
      const res = await adminRetryJob(jobId);
      toast({ title: "Job retried", description: `New job #${res.new_job_id} queued` });
      fetchJobs();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Retry failed";
      toast({ title: "Error", description: msg, variant: "destructive" });
    }
  };

  const handleDeleteExport = async (jobId: number) => {
    try {
      await adminDeleteExport(jobId);
      toast({ title: "Export deleted", description: `Export for job #${jobId} removed` });
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Delete failed";
      toast({ title: "Error", description: msg, variant: "destructive" });
    }
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await adminChangePassword(oldPw, newPw);
      toast({ title: "Password changed" });
      setShowPasswordForm(false);
      setOldPw("");
      setNewPw("");
    } catch {
      toast({ title: "Error", description: "Old password is incorrect", variant: "destructive" });
    }
  };

  if (!token) {
    return (
      <section id="admin" className="py-16 md:py-24">
        <div className="mx-auto max-w-sm px-4">
          <h2 className="text-2xl font-bold text-center mb-6">{s.loginTitle}</h2>
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="text-xs text-muted-foreground block mb-1">{s.emailLabel}</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required className="w-full h-9 px-3 rounded-md border border-border bg-background text-sm" />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">{s.passwordLabel}</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required className="w-full h-9 px-3 rounded-md border border-border bg-background text-sm" />
            </div>
            <button type="submit" disabled={loggingIn} className="w-full h-9 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50">
              {loggingIn ? s.loading : s.loginCta}
            </button>
          </form>
        </div>
      </section>
    );
  }

  return (
    <section id="admin" className="py-16 md:py-24">
      <div className="mx-auto max-w-5xl px-4">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold">{s.dashboardTitle}</h2>
          <div className="flex items-center gap-2">
            <button onClick={() => setShowPasswordForm(!showPasswordForm)} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
              <Lock className="h-3 w-3" /> Change Password
            </button>
            <button onClick={handleLogout} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
              <LogOut className="h-3 w-3" /> Logout
            </button>
          </div>
        </div>

        {showPasswordForm && (
          <form onSubmit={handleChangePassword} className="mb-6 p-4 rounded-lg border border-border bg-muted/30 space-y-3">
            <h3 className="text-sm font-medium">Change Password</h3>
            <div className="flex gap-2">
              <input type="password" placeholder="Old password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} required className="flex-1 h-8 px-2 rounded border border-border bg-background text-xs" />
              <input type="password" placeholder="New password" value={newPw} onChange={(e) => setNewPw(e.target.value)} required className="flex-1 h-8 px-2 rounded border border-border bg-background text-xs" />
              <button type="submit" className="h-8 px-3 rounded bg-primary text-primary-foreground text-xs font-medium">Save</button>
            </div>
          </form>
        )}

        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/50">
                <th className="px-3 py-2.5 text-left font-medium text-muted-foreground text-xs uppercase tracking-wider">ID</th>
                <th className="px-3 py-2.5 text-left font-medium text-muted-foreground text-xs uppercase tracking-wider">Source</th>
                <th className="px-3 py-2.5 text-left font-medium text-muted-foreground text-xs uppercase tracking-wider">Query</th>
                <th className="px-3 py-2.5 text-left font-medium text-muted-foreground text-xs uppercase tracking-wider">Status</th>
                <th className="px-3 py-2.5 text-left font-medium text-muted-foreground text-xs uppercase tracking-wider">Leads</th>
                <th className="px-3 py-2.5 text-left font-medium text-muted-foreground text-xs uppercase tracking-wider">Payment</th>
                <th className="px-3 py-2.5 text-left font-medium text-muted-foreground text-xs uppercase tracking-wider">Created</th>
                <th className="px-3 py-2.5 text-left font-medium text-muted-foreground text-xs uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loadingJobs && (
                <tr><td colSpan={8} className="px-3 py-8 text-center text-sm text-muted-foreground">{s.loading}</td></tr>
              )}
              {!loadingJobs && jobs.length === 0 && (
                <tr><td colSpan={8} className="px-3 py-8 text-center text-sm text-muted-foreground">{s.noJobs}</td></tr>
              )}
              {!loadingJobs && jobs.map((job) => (
                <tr key={job.id} className="border-b border-border last:border-0">
                  <td className="px-3 py-2.5 text-xs">#{job.id}</td>
                  <td className="px-3 py-2.5 text-xs">{job.source}</td>
                  <td className="px-3 py-2.5 text-xs max-w-[200px] truncate">{job.query || "-"}</td>
                  <td className="px-3 py-2.5 text-xs">
                    <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${
                      job.status === "completed" ? "bg-green-500/10 text-green-400" :
                      job.status === "failed" ? "bg-red-500/10 text-red-400" :
                      job.status === "running" ? "bg-blue-500/10 text-blue-400" :
                      "bg-yellow-500/10 text-yellow-400"
                    }`}>
                      {job.status}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-xs">{job.total_found}</td>
                  <td className="px-3 py-2.5 text-xs">{job.payment_status || "unpaid"}</td>
                  <td className="px-3 py-2.5 text-xs text-muted-foreground">{new Date(job.created_at).toLocaleDateString()}</td>
                  <td className="px-3 py-2.5 text-xs">
                    <div className="flex items-center gap-1">
                      {job.status === "failed" && (
                        <button onClick={() => handleRetry(job.id)} className="inline-flex items-center gap-0.5 px-2 py-1 rounded bg-muted/50 text-muted-foreground hover:text-foreground text-[10px]" title="Retry">
                          <RefreshCw className="h-3 w-3" /> {s.retryCta}
                        </button>
                      )}
                      {job.status === "completed" && (
                        <button onClick={() => handleDeleteExport(job.id)} className="inline-flex items-center gap-0.5 px-2 py-1 rounded bg-muted/50 text-red-400 hover:text-red-300 text-[10px]" title="Delete export">
                          <Trash2 className="h-3 w-3" /> {s.deleteCta}
                        </button>
                      )}
                      {job.status === "failed" && (
                        <span className="text-[10px] text-muted-foreground flex items-center gap-0.5" title={job.error_message || ""}>
                          <AlertCircle className="h-3 w-3" /> {job.error_message ? job.error_message.slice(0, 30) : ""}
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
