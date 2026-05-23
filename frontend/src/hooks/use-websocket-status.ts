import { useEffect, useRef, useState } from "react";
import { getStatus, type StatusResponse } from "@/lib/api";

const WS_BASE = import.meta.env.VITE_API_URL?.replace(/^http/, "ws") || `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api`;

export function useWebSocketStatus(pollInterval = 15000) {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const ws = useRef<WebSocket | null>(null);
  const mountedRef = useRef(true);
  const pollTimerRef = useRef<ReturnType<typeof setInterval>>();

  useEffect(() => {
    mountedRef.current = true;

    function startPolling() {
      clearInterval(pollTimerRef.current);
      setLoading(true);
      getStatus()
        .then((s) => { if (mountedRef.current) { setStatus(s); setLoading(false); } })
        .catch(() => { if (mountedRef.current) setLoading(false); });
      pollTimerRef.current = setInterval(() => {
        getStatus()
          .then((s) => { if (mountedRef.current) setStatus(s); })
          .catch(() => {});
      }, pollInterval);
    }

    function startWebSocket() {
      try {
        const socket = new WebSocket(`${WS_BASE}/ws/status`);
        socket.onmessage = (event) => {
          if (mountedRef.current) {
            try {
              setStatus(JSON.parse(event.data));
              setLoading(false);
            } catch {}
          }
        };
        socket.onclose = () => {
          if (mountedRef.current) startPolling();
        };
        socket.onerror = () => {
          socket.close();
        };
        ws.current = socket;
      } catch {
        startPolling();
      }
    }

    startWebSocket();

    return () => {
      mountedRef.current = false;
      if (ws.current) ws.current.close();
      clearInterval(pollTimerRef.current);
    };
  }, [pollInterval]);

  return { status, loading };
}
