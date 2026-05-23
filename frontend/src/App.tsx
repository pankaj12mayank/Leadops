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
    <ToastProvider>
      <BrowserRouter>
        <Suspense fallback={<PageLoading />}>
          <Routes>
            <Route element={<AppLayout />}>
              <Route path="/" element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
              <Route path="/scrapers" element={<ErrorBoundary><Scrapers /></ErrorBoundary>} />
              <Route path="/logs" element={<ErrorBoundary><Logs /></ErrorBoundary>} />
              <Route path="/exports" element={<ErrorBoundary><Exports /></ErrorBoundary>} />
              <Route path="/settings" element={<ErrorBoundary><Settings /></ErrorBoundary>} />
            </Route>
          </Routes>
        </Suspense>
        <Toaster />
      </BrowserRouter>
    </ToastProvider>
  );
}
