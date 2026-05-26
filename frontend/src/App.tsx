import { useState, useCallback, useRef, useEffect } from "react";
import { Helmet, HelmetProvider } from "react-helmet-async";
import { Toaster } from "@/components/ui/toaster";
import { ToastProvider } from "@/hooks/use-toast";
import AdminSection from "@/components/sections/AdminSection";
import SearchSection from "@/components/sections/SearchSection";
import ResultsSection from "@/components/sections/ResultsSection";
import { useSiteContent } from "@/hooks/useSiteContent";
import { getJob, type JobInfo } from "@/lib/api";
import { ArrowDown, Database, Download, Eye, CreditCard, ChevronDown, Shield } from "lucide-react";

const JOB_STORAGE_KEY = "leadops_last_job_id";

function AppContent() {
  const { content } = useSiteContent();
  const [currentJob, setCurrentJob] = useState<JobInfo | null>(null);
  const [showAdmin, setShowAdmin] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const stored = sessionStorage.getItem(JOB_STORAGE_KEY);
    if (stored) {
      const jobId = parseInt(stored, 10);
      if (!isNaN(jobId)) {
        getJob(jobId).then((res) => {
          if (res.job) setCurrentJob(res.job);
        }).catch(() => {});
      }
    }
  }, []);

  const handleJobStarted = useCallback((jobId: number) => {
    if (pollRef.current) clearInterval(pollRef.current);
    sessionStorage.setItem(JOB_STORAGE_KEY, String(jobId));
    const poll = setInterval(async () => {
      try {
        const res = await getJob(jobId);
        setCurrentJob(res.job);
        if (res.job.status === "completed" || res.job.status === "failed" || res.job.status === "cancelled") {
          clearInterval(poll);
          pollRef.current = null;
        }
      } catch {
        clearInterval(poll);
        pollRef.current = null;
      }
    }, 2000);
    pollRef.current = poll;
  }, []);

  const seo = content?.seo;
  const brand = content?.brand;
  const hero = content?.hero;
  const features = content?.features;
  const search = content?.search;
  const results = content?.results;
  const pricing = content?.pricing;
  const faq = content?.faq;
  const nav = content?.nav;

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Helmet>
        <title>{seo?.title || "LeadOps"}</title>
        <meta name="description" content={seo?.metaDescription || "Business lead extraction tool"} />
        <meta name="keywords" content={seo?.keywords || "lead generation, business leads"} />
      </Helmet>

      {/* Nav */}
      <nav className="sticky top-0 z-50 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 h-14">
          <span
            className="font-bold text-sm cursor-pointer"
            onClick={() => setShowAdmin(false)}
          >
            {brand?.name || "LeadOps"}
          </span>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            {!showAdmin && (nav?.links || []).map((link) => (
              <a key={link.href} href={link.href} className="hover:text-foreground transition-colors">{link.label}</a>
            ))}
            <button
              onClick={() => setShowAdmin(!showAdmin)}
              className="inline-flex items-center gap-1 hover:text-foreground transition-colors"
            >
              <Shield className="h-3 w-3" /> Admin
            </button>
          </div>
        </div>
      </nav>

      {showAdmin ? (
        <AdminSection />
      ) : (
        <>
      {/* Hero */}
      <section className="py-20 md:py-32 text-center">
        <div className="mx-auto max-w-3xl px-4">
          <h1 className="text-4xl md:text-6xl font-bold tracking-tight mb-4" dangerouslySetInnerHTML={{ __html: hero?.title || "Extract Business Leads<br />in Minutes" }} />
          <p className="text-lg text-muted-foreground mb-8 max-w-xl mx-auto">
            {hero?.subtitle || "Scrape Clutch, GoodFirms, Google Maps, and LinkedIn. Preview results, pay to unlock, and download clean CSV exports."}
          </p>
          <a
            href="#search"
            className="inline-flex items-center justify-center h-11 px-6 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity"
          >
            {hero?.cta || "Start Extracting"} <ArrowDown className="ml-2 h-4 w-4" />
          </a>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="py-16 md:py-24 bg-muted/30">
        <div className="mx-auto max-w-5xl px-4">
          <h2 className="text-2xl md:text-3xl font-bold text-center mb-12">{features?.heading || "How It Works"}</h2>
          <div className="grid gap-6 md:grid-cols-4">
            {(features?.items || []).map((f) => {
              const icons = [Database, Eye, CreditCard, Download];
              const Icon = icons[features?.items?.indexOf(f) ?? 0] || Database;
              return (
                <div key={f.title} className="text-center p-6">
                  <div className="inline-flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10 mb-4">
                    <Icon className="h-6 w-6 text-primary" />
                  </div>
                  <h3 className="font-semibold mb-1">{f.title}</h3>
                  <p className="text-xs text-muted-foreground">{f.description}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* Search */}
      <SearchSection
        heading={search?.heading}
        subtitle={search?.subtitle}
        labels={search?.labels}
        placeholders={search?.placeholders}
        buttonLabel={search?.button}
        onJobStarted={handleJobStarted}
      />

      {/* Results */}
      <ResultsSection
        job={currentJob}
        strings={results}
      />

      {/* Pricing */}
      <section id="pricing" className="py-16 md:py-24">
        <div className="mx-auto max-w-3xl px-4">
          <h2 className="text-2xl md:text-3xl font-bold text-center mb-2">{pricing?.heading || "Simple Pricing"}</h2>
          <p className="text-muted-foreground text-center text-sm mb-10">{pricing?.subtitle || "Pay once per export. No subscriptions."}</p>
          <div className="max-w-sm mx-auto">
            <div className="rounded-xl border border-border p-8 text-center">
              <p className="text-muted-foreground text-sm mb-2">{pricing?.perExport || "Per Export"}</p>
              <p className="text-5xl font-bold mb-1">{pricing?.price || "$9"}</p>
              <p className="text-sm text-muted-foreground mb-6">{pricing?.priceDescription || "One-time payment for full CSV download"}</p>
              <ul className="text-left text-sm space-y-2 mb-8">
                {(pricing?.features || []).map((item) => (
                  <li key={item} className="flex items-center gap-2">
                    <span className="text-green-400">✓</span> {item}
                  </li>
                ))}
              </ul>
              <a
                href="#search"
                className="inline-flex items-center justify-center h-11 w-full rounded-md bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity"
              >
                {pricing?.cta || "Get Started"}
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="py-16 md:py-24 bg-muted/30">
        <div className="mx-auto max-w-2xl px-4">
          <h2 className="text-2xl md:text-3xl font-bold text-center mb-10">{faq?.heading || "FAQ"}</h2>
          <div className="space-y-4">
            {(faq?.items || []).map((item) => (
              <details key={item.question} className="group rounded-lg border border-border p-4">
                <summary className="flex items-center justify-between cursor-pointer text-sm font-medium">
                  {item.question}
                  <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180" />
                </summary>
                <p className="mt-3 text-sm text-muted-foreground">{item.answer}</p>
              </details>
            ))}
          </div>
        </div>
      </section>
    </>
    )}
    </div>
  );
}

export default function App() {
  return (
    <HelmetProvider>
      <ToastProvider>
        <AppContent />
        <Toaster />
      </ToastProvider>
    </HelmetProvider>
  );
}
