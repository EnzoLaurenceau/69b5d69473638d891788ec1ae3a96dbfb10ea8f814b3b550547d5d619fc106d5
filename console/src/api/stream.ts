// Abonnement au WS /v1/stream d'un run. Reconnexion avec since_seq (Annexe D.3).
import type { StreamEvent } from "./types";

export interface StreamHandle {
  close: () => void;
}

interface StreamOpts {
  onEvent: (ev: StreamEvent) => void;
  onStatus?: (open: boolean) => void;
}

/**
 * Ouvre le WS pour un run et pousse chaque event à onEvent. Le token passe en query
 * (le WS ne porte pas d'en-tête Authorization). Reprend à `sinceSeq` après reconnexion.
 */
export function openStream(runId: string, token: string, opts: StreamOpts): StreamHandle {
  let closed = false;
  let sinceSeq = 0;
  let ws: WebSocket | null = null;

  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const connect = () => {
    if (closed) return;
    const url = `${proto}://${window.location.host}/v1/stream`
      + `?run_id=${encodeURIComponent(runId)}`
      + `&token=${encodeURIComponent(token)}`
      + `&since_seq=${sinceSeq}`;
    ws = new WebSocket(url);

    ws.onopen = () => opts.onStatus?.(true);
    ws.onmessage = (msg) => {
      let ev: StreamEvent;
      try {
        ev = JSON.parse(msg.data as string);
      } catch {
        return;
      }
      if (typeof ev.seq === "number") sinceSeq = Math.max(sinceSeq, ev.seq);
      if (ev.type === "heartbeat") return;
      opts.onEvent(ev);
    };
    ws.onclose = () => {
      opts.onStatus?.(false);
      // Reconnexion douce tant que non fermé volontairement (le run peut continuer).
      if (!closed) setTimeout(connect, 1000);
    };
    ws.onerror = () => ws?.close();
  };

  connect();
  return {
    close: () => {
      closed = true;
      ws?.close();
    },
  };
}
