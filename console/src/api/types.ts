// Types du contrat /v1 (cf. PLAN_PLATEFORME_INFERENCE.md, Annexes A & D).

export type RunStatus =
  | "queued" | "running" | "done" | "error" | "cancelled" | "cancelling";

export interface RunSnapshot {
  run_id: string;
  task: string;
  agent: string | null;
  status: RunStatus;
  tokens_in: number;
  tokens_out: number;
  cost: number;
  created: number;
  started: number | null;
  ended: number | null;
  result: string | null;
}

/** Enveloppe d'event du WS /v1/stream (Annexe D). */
export interface StreamEvent {
  v: number;
  run_id: string;
  seq: number;
  ts: number;
  type: string;
  data: Record<string, unknown>;
}

export interface Metrics {
  tokens_in: number;
  tokens_out: number;
  cost: number;
  savings_pct: number;
  agents_active: number;
}

export interface QuotaResource {
  used: number;
  limit: number;
  window?: string;
}

/** Sortie de forge_quota.report() : `limits` et `usage` sont deux dictionnaires
 *  PARALLÈLES indexés par ressource — ce n'est pas une liste de {used, limit}.
 *  L'index signature garde la forme tolérante pour un serveur plus ancien. */
export interface QuotaReport {
  tenant?: string;
  limits?: Record<string, number>;
  usage?: Record<string, number>;
  window_seconds?: number;
  [resource: string]: QuotaResource | Record<string, number> | string | number | undefined;
}

/** Source du chiffre affiché. C'est le champ à lire EN PREMIER :
 *  `remote`   lu chez le fournisseur ;
 *  `local`    mesuré par ce dépôt (ledger des appels) ;
 *  `declared` rien de mesuré encore — seul le point de départ humain est connu. */
export type BudgetSource = "remote" | "local" | "declared";

/** Sortie de mimo_budget.report() — plan d'abonnement MiMo, axe FOURNISSEUR.
 *  Distinct de QuotaReport, qui est l'axe CLIENT sur une fenêtre glissante. */
export interface MimoBudget {
  provider: string;
  period: string;                 // mois calendaire UTC (YYYY-MM)
  plan_tokens: number;
  used_tokens: number;
  remaining_tokens: number;
  pct: number;
  alert_pct: number;
  over_alert: boolean;
  source: BudgetSource;
  baseline_tokens: number;        // point de départ déclaré, PAS mesuré
  ledger_billed_tokens: number;
  ledger_real_tokens: number;     // non arrondi — l'écart avec le facturé = le round-up
  calls: number;
  measured_since: number | null;  // epoch du 1er appel mesuré ce mois
  configured: boolean;            // MIMO_API_KEY réellement présente
}

export interface AgentInfo {
  name: string;
  status: string;
}

export interface GraphNode {
  type?: string;              // label du nœud (Agent, Project, Concept, …)
  key?: string;               // identifiant canonique (name / id / adr_id)
  group?: string;             // sous-groupe (role/status/category/…) pour les "régions" niveau 2
  [k: string]: unknown;
}

export interface GraphEdge {
  source: string;
  target: string;
  type?: string;              // relation (EXECUTES, RECALLS, …)
  source_type?: string;
  target_type?: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated?: boolean;        // un type a atteint le plafond serveur — rien coupé en silence
  focus?: string;
  stats?: Record<string, number>;
  note?: string;
}

// Plus de `free` : décision 2026-07-25, aucun tier gratuit ne reste (trop instables).
// Un tier retiré reste affiché plutôt que masqué — le cacher inviterait à le re-brancher
// sans savoir pourquoi il était parti.
export type RouterTierKind = "subscription" | "paid" | "removed";

export interface RouterTier {
  name: string;
  kind: RouterTierKind;
  wired: boolean;         // le code du routeur contient encore une branche
  available: boolean;     // une clé est réellement configurée ici et maintenant
  detail: string;
}

export interface RouterTiers {
  tiers: RouterTier[];
  default_policy: string;
  free_tier_available: boolean;   // false — plus aucune destination gratuite pour le volume
}

/** Une tâche du backlog persistant (`forge_backlog.py`). */
export interface BacklogTask {
  id: string;
  epic: string;
  title: string;
  state: string;          // pending | ready | in_progress | blocked | done | cancelled
  complexity: string;     // S | M | H
  effort_days: number;
  actual_days: number;
  est_tokens: number;
  actual_tokens: number;
  assignee: string;
  session_id: string;
  depends_on: string[];
  artifacts: string[];
  files: string[];
  retries: number;
  block_reason: string;
  provenance: string;
  notes: string;
  created_at: number;
  updated_at: number;
  started_at: number;
  completed_at: number;
}

export interface BacklogSummary {
  tasks: number;
  cycles: string[][];
  dangling_dependencies: string[][];
  ready: string[];
  by_state: Record<string, number>;
}

export interface EpicSummary {
  [epic: string]: {
    tasks: number;
    done: number;
    pct_done: number;
    effort_days: number;
    actual_days: number;
  };
}

export interface BacklogData {
  summary: BacklogSummary;
  epic_summary: EpicSummary;
  critical_path: {
    duration_days: number;
    path: string[];
    critical: string[];
    schedule: Record<string, {
      early_start: number;
      early_finish: number;
      late_start: number;
      late_finish: number;
      slack: number;
    }>;
  };
  tasks: BacklogTask[];
}

/** Une tâche du board kanban (`00_CORE/forge_dispatch/kanban.py`). */
export interface BoardTask {
  id: string;
  name: string;
  status: string;           // pending | in_progress | done | blocked (brut, jamais masqué)
  est?: string;             // XS | S | M | L
  day?: number;
  files?: string[];
  result?: string;
  block_reason?: string;
}

export type BoardColumn = "todo" | "doing" | "done" | "blocked";

/** Sortie de `/v1/orchestrator/board`. `scope` dit à QUI est ce board :
 *  `tenant` = celui du tenant courant ; `global` = celui de l'opérateur, servi en repli
 *  quand le tenant n'en a pas (uniquement sur une instance mono-tenant). */
export interface BoardData {
  columns: Record<BoardColumn, BoardTask[]>;
  counts: Record<BoardColumn, number>;
  scope: "tenant" | "global";
  parent_task?: string;
  updated?: string | null;
  note?: string;
}
