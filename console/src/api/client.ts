// Client REST du contrat /v1. Toutes les requêtes portent le Bearer du tenant courant.
// Le token vit en mémoire (cf. auth/AuthContext) — jamais localStorage (règle Fable 5).

import type {
  AgentInfo, BacklogData, BoardData, GraphData, Metrics, MimoBudget, QuotaReport, RouterTiers, RunSnapshot,
} from "./types";

const BASE = "/v1"; // proxifié vers :7777 par Vite en dev

export class ApiError extends Error {
  constructor(public status: number, public body: unknown) {
    super(`HTTP ${status}`);
  }
}

async function req<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init?.headers || {}),
    },
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, body);
  return body as T;
}

export interface RunRequest {
  task: string;
  agent?: string;
  budget_tokens?: number;
}

export const api = {
  runAgent: (token: string, r: RunRequest) =>
    req<{ run_id: string; status: string }>("/agents/run", token, {
      method: "POST",
      body: JSON.stringify(r),
    }),

  getRun: (token: string, runId: string) =>
    req<RunSnapshot>(`/runs/${runId}`, token),

  listRuns: (token: string, limit = 50) =>
    req<{ runs: RunSnapshot[] }>(`/runs?limit=${limit}`, token),

  cancelRun: (token: string, runId: string) =>
    req<{ run_id: string; status: string }>(`/runs/${runId}/cancel`, token, { method: "POST" }),

  getMetrics: (token: string) => req<Metrics>("/metrics", token),

  getQuota: (token: string) => req<QuotaReport>("/quota", token),

  /** Solde du plan MiMo (axe fournisseur) — pas le quota du tenant. */
  getMimoBudget: (token: string) => req<MimoBudget>("/budget/mimo", token),

  getAgents: (token: string) => req<{ agents: AgentInfo[] }>("/agents", token),

  getGraph: (token: string) => req<GraphData>("/graph", token),

  getBoard: (token: string) => req<BoardData>("/orchestrator/board", token),

  getBacklog: (token: string) => req<BacklogData>("/backlog", token),

  getRouterTiers: (token: string) => req<RouterTiers>("/router/tiers", token),
};

/** Vérifie qu'un token est valide (résout un tenant) en tapant un endpoint léger. */
export async function checkToken(token: string): Promise<boolean> {
  try {
    await api.getMetrics(token);
    return true;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return false;
    // Autre erreur (503, réseau) → on considère le token comme accepté, l'app affichera l'état.
    return true;
  }
}
