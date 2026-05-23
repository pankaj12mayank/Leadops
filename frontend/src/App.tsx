import { Suspense, lazy } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AppLayout } from "@/components/layout/AppLayout";
import { Toaster } from "@/components/ui/toaster";
import { PageLoading } from "@/components/shared/LoadingState";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { ToastProvider } from "@/hooks/use-toast";

const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Scrapers = lazy(() => import("@/pages/Scrapers"));
const Logs = lazy(() => import("@/pages/Logs"));
const Exports = lazy(() => import("@/pages/Exports"));
const Settings = lazy(() => import("@/pages/Settings"));

export default function App() {
  return (
    <ErrorBoundary>
      <ToastProvider>
        <BrowserRouter>
          <Suspense fallback={<PageLoading />}>
            <Routes>
              <Route element={<AppLayout />}>
                <Route path="/" element={<Dashboard />} />
                <Route path="/scrapers" element={<Scrapers />} />
                <Route path="/logs" element={<Logs />} />
                <Route path="/exports" element={<Exports />} />
                <Route path="/settings" element={<Settings />} />
              </Route>
            </Routes>
          </Suspense>
          <Toaster />
        </BrowserRouter>
      </ToastProvider>
    </ErrorBoundary>
  );
}
