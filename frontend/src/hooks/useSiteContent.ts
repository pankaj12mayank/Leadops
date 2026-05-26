import { useEffect, useState } from "react";
import { api, type SiteContent } from "@/lib/api";

const CACHE_KEY = "leadops_site_content";

function fromCache(): SiteContent | null {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function toCache(data: SiteContent) {
  try {
    sessionStorage.setItem(CACHE_KEY, JSON.stringify(data));
  } catch {
    /* noop */
  }
}

export function useSiteContent() {
  const [content, setContent] = useState<SiteContent | null>(fromCache);
  const [loading, setLoading] = useState(!content);

  useEffect(() => {
    if (content) return;
    api
      .get("/content")
      .then((res) => {
        const data = res.data as SiteContent;
        setContent(data);
        toCache(data);
      })
      .catch(() => {
        /* use defaults if fetch fails */
      })
      .finally(() => setLoading(false));
  }, [content]);

  return { content, loading };
}
