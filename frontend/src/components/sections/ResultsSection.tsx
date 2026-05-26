import { useEffect, useState } from "react";
import { getJobLeads, getJobExportUrl, getPaymentStatus, getPreviewStatus, unlockPreview, createCheckoutSession, type JobInfo, type LeadRow } from "@/lib/api";
import { PREVIEW_COLUMNS, SOURCE_COLORS } from "@/lib/types";
import { toast } from "@/hooks/use-toast";
import { Download, Eye, Lock, CreditCard } from "lucide-react";

interface ResultsSectionProps {
  job: JobInfo | null;
  strings?: {
    empty?: string;
    locked?: string;
    unlockCta?: string;
    downloadCta?: string;
    payCta?: string;
  };
}

const PREVIEW_LIMIT = 3;

export default function ResultsSection({ job, strings = {} }: ResultsSectionProps) {
  const [leads, setLeads] = useState<LeadRow[]>([]);
  const [previewed, setPreviewed] = useState(false);
  const [paid, setPaid] = useState(false);
  const [unlocking, setUnlocking] = useState(false);
  const [paying, setPaying] = useState(false);

  const s = { empty: "Run a search above to see preview results here.", locked: "more leads locked", unlockCta: "Unlock Full Results", downloadCta: "Download CSV", payCta: "Download CSV ($9)", ...strings };

  useEffect(() => {
    if (!job || job.status !== "completed") {
      setLeads([]);
      setPreviewed(false);
      setPaid(false);
      return;
    }
    getJobLeads(job.id)
      .then((r) => setLeads(r.leads || []))
      .catch(() => {});
    getPreviewStatus(job.id)
      .then((r) => setPreviewed(r.previewed))
      .catch(() => {});
    getPaymentStatus(job.id)
      .then((r) => setPaid(r.paid))
      .catch(() => {});
  }, [job?.id, job?.status]);

  const handleUnlock = async () => {
    if (!job) return;
    setUnlocking(true);
    try {
      const res = await unlockPreview(job.id);
      if (res.granted) {
        setPreviewed(true);
        toast({ title: "Preview unlocked", description: "All leads are now visible" });
      } else {
        toast({ title: "Already previewed", description: "This IP has already used its free preview" });
      }
    } catch {
      toast({ title: "Error", description: "Failed to unlock preview", variant: "destructive" });
    } finally {
      setUnlocking(false);
    }
  };

  const handlePay = async () => {
    if (!job) return;
    setPaying(true);
    try {
      const res = await createCheckoutSession(job.id, window.location.href, window.location.href);
      if (res.checkout_url) {
        window.location.href = res.checkout_url;
      } else {
        toast({ title: "Error", description: "Failed to create checkout session", variant: "destructive" });
      }
    } catch {
      toast({ title: "Error", description: "Could not initiate payment", variant: "destructive" });
    } finally {
      setPaying(false);
    }
  };

  const downloadUrl = job && job.status === "completed" && paid ? getJobExportUrl(job.id) : null;

  if (!job) {
    return (
      <section id="results" className="py-16 md:py-24 bg-muted/30">
        <div className="mx-auto max-w-4xl px-4 text-center">
          <h2 className="text-2xl md:text-3xl font-bold mb-2">Results</h2>
          <p className="text-muted-foreground text-sm">{s.empty}</p>
        </div>
      </section>
    );
  }

  const visible = job.status === "completed" && leads.length > 0;
  const displayLeads = (previewed || paid) ? leads : leads.slice(0, PREVIEW_LIMIT);
  const lockedCount = (previewed || paid) ? 0 : Math.max(0, leads.length - PREVIEW_LIMIT);

  return (
    <section id="results" className="py-16 md:py-24 bg-muted/30">
      <div className="mx-auto max-w-4xl px-4">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-2xl md:text-3xl font-bold">Results</h2>
          <span className={`text-xs px-2 py-0.5 rounded-full border ${SOURCE_COLORS[job.source] || ""}`}>
            {job.source}
          </span>
        </div>
        <p className="text-muted-foreground text-sm mb-6">
          Status: <span className="font-medium">{job.status}</span>
          {job.status === "completed" && ` · ${leads.length} leads`}
          {!previewed && !paid && job.status === "completed" && leads.length > PREVIEW_LIMIT && (
            <span className="text-muted-foreground"> · showing {PREVIEW_LIMIT}</span>
          )}
        </p>

        {job.status === "running" && (
          <div className="text-center py-12 text-muted-foreground">
            <div className="animate-spin h-6 w-6 border-2 border-muted-foreground border-t-transparent rounded-full mx-auto mb-3" />
            <p className="text-sm">Scraping in progress...</p>
          </div>
        )}

        {job.status === "failed" && (
          <div className="text-center py-12">
            <p className="text-sm text-red-400">Job failed: {job.error_message || "Unknown error"}</p>
          </div>
        )}

        {job.status === "queued" && (
          <div className="text-center py-12 text-muted-foreground">
            <p className="text-sm">Job is queued — waiting to run...</p>
          </div>
        )}

        {visible && (
          <>
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/50">
                    {PREVIEW_COLUMNS.map((col) => (
                      <th key={col} className="px-3 py-2.5 text-left font-medium text-muted-foreground text-xs uppercase tracking-wider">
                        {col.replace(/_/g, " ")}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {displayLeads.map((lead) => (
                    <tr key={lead.id} className="border-b border-border last:border-0">
                      {PREVIEW_COLUMNS.map((col) => (
                        <td key={col} className="px-3 py-2.5 text-xs">
                          {lead[col as keyof LeadRow] ?? ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                  {lockedCount > 0 && !previewed && !paid && (
                    <tr>
                      <td colSpan={PREVIEW_COLUMNS.length} className="px-3 py-4 text-center">
                        <div className="blur-sm select-none text-muted-foreground text-xs">
                          {Array.from({ length: Math.min(lockedCount, 3) }).map((_, i) => (
                            <div key={i} className="py-1">********</div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {lockedCount > 0 && !previewed && !paid && (
              <div className="mt-4 text-center">
                <p className="text-sm text-muted-foreground mb-3">
                  <Lock className="h-4 w-4 inline mr-1" />
                  {lockedCount} {s.locked}
                </p>
                <button
                  onClick={handleUnlock}
                  disabled={unlocking}
                  className="inline-flex items-center justify-center h-9 px-4 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  <Eye className="h-4 w-4 mr-2" />
                  {unlocking ? "Unlocking..." : s.unlockCta}
                </button>
              </div>
            )}

            {previewed && !paid && (
              <div className="mt-4 text-center">
                <p className="text-sm text-muted-foreground mb-3">All leads visible. Download the full CSV export for $9.</p>
                <button
                  onClick={handlePay}
                  disabled={paying}
                  className="inline-flex items-center justify-center h-9 px-4 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  <CreditCard className="h-4 w-4 mr-2" />
                  {paying ? "Redirecting to Stripe..." : s.payCta}
                </button>
              </div>
            )}

            {paid && downloadUrl && (
              <div className="mt-4 text-center">
                <a
                  href={downloadUrl}
                  download
                  className="inline-flex items-center justify-center h-9 px-4 rounded-md border border-input bg-transparent text-sm font-medium shadow-sm hover:bg-accent hover:text-accent-foreground transition-colors"
                >
                  <Download className="h-4 w-4 mr-2" /> {s.downloadCta}
                </a>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
