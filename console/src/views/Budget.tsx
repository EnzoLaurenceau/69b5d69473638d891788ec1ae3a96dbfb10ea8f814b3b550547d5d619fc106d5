import { Card, Icon, MetricCard, ProgressBar, StatusBadge } from "../design-system";
import { ViewHeader } from "../components/Shell";
import { usePoll } from "../components/usePoll";
import { api } from "../api/client";
import type { BudgetSource, MimoBudget, QuotaReport, QuotaResource } from "../api/types";
import { useToken } from "../auth/AuthContext";

const LABELS: Record<string, string> = {
  storage: "stockage",
  storage_bytes: "stockage",
  requests: "requêtes",
  llm_tokens: "tokens llm",
};

// D'où vient le chiffre. `declared` doit alerter : c'est un solde annoncé par un humain,
// pas une mesure — l'afficher comme un fait referait la promesse que S-02 a retirée au routeur.
const SOURCE: Record<BudgetSource, { status: "info" | "warn" | "idle"; label: string }> = {
  remote: { status: "info", label: "lu chez le fournisseur" },
  local: { status: "idle", label: "mesuré ici" },
  declared: { status: "warn", label: "déclaré, pas encore mesuré" },
};

/** 11 000 000 000 est illisible dans un tableau de bord. */
function fmtTokens(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(n >= 1e10 ? 1 : 2)} Md`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} M`;
  if (n >= 1e3) return `${Math.round(n / 1e3)} k`;
  return String(Math.round(n));
}

function isResource(v: unknown): v is QuotaResource {
  return typeof v === "object" && v !== null && "used" in v && "limit" in v;
}

/** `forge_quota.report()` renvoie `limits` et `usage` séparés ; la vue veut des paires.
 *  Sans cet appariement le filtre ne trouvait AUCUNE ressource et la carte restait vide. */
function pairResources(q: QuotaReport | null): [string, QuotaResource][] {
  const limits = q?.limits;
  const usage = q?.usage;
  if (limits && usage) {
    return Object.keys(limits).map((k) => [
      k,
      { used: Number(usage[k] ?? 0), limit: Number(limits[k] ?? 0) },
    ]);
  }
  // Repli : serveur renvoyant déjà des {used, limit} par ressource.
  return Object.entries(q ?? {}).filter(([, v]) => isResource(v)) as [string, QuotaResource][];
}

/** Plan d'abonnement MiMo — axe FOURNISSEUR (mensuel, commun à tous les tenants),
 *  à ne pas confondre avec les quotas ci-dessous qui sont l'axe CLIENT (fenêtre glissante). */
function MimoPlan({ b }: { b: MimoBudget }) {
  const src = SOURCE[b.source] ?? SOURCE.declared;
  // Écart facturé / réel = ce que coûte l'arrondi au bloc de 1000. Chiffre brut du levier S-06.
  const overhead =
    b.ledger_real_tokens > 0
      ? Math.round(((b.ledger_billed_tokens - b.ledger_real_tokens) / b.ledger_real_tokens) * 100)
      : null;

  return (
    <Card style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)", marginBottom: "var(--space-6)" }}>
      {/* `wrap` partout : jusqu'à trois badges peuvent cohabiter avec le titre. Sans lui,
          l'en-tête se disloque dès qu'on rétrécit la fenêtre. */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "var(--space-2)" }}>
        <span style={{ fontSize: "var(--text-h3)", fontWeight: 500, whiteSpace: "nowrap" }}>
          plan {b.provider.toLowerCase()} — {b.period}
        </span>
        <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
          <StatusBadge status={src.status}>{src.label}</StatusBadge>
          {!b.configured && <StatusBadge status="warn">clé absente</StatusBadge>}
          {b.over_alert && <StatusBadge status="error">seuil {b.alert_pct} % franchi</StatusBadge>}
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "baseline", gap: "var(--space-2)", flexWrap: "wrap", fontFamily: "var(--font-mono)" }}>
        <span style={{ fontSize: "32px", color: "var(--text-primary)", whiteSpace: "nowrap" }}>{fmtTokens(b.remaining_tokens)}</span>
        <span style={{ fontSize: "13px", color: "var(--text-muted)" }}>
          restants sur {fmtTokens(b.plan_tokens)} · {fmtTokens(b.used_tokens)} consommés ({b.pct} %)
        </span>
      </div>

      <ProgressBar value={b.pct} max={100} height={8} />

      <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-4)", fontSize: "12px", fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
        <span>point de départ déclaré : {fmtTokens(b.baseline_tokens)}</span>
        <span>mesuré ici : {fmtTokens(b.ledger_billed_tokens)} sur {b.calls} appel{b.calls > 1 ? "s" : ""}</span>
        {overhead !== null && <span>round-up : +{overhead} % vs réel</span>}
      </div>

      {b.source === "declared" && (
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
          <Icon name="alert-triangle" size={16} color="var(--forge-amber-400)" />
          <span style={{ fontSize: "13px", color: "var(--text-secondary)" }}>
            aucun appel mesuré ce mois — ce solde vient d'une déclaration, pas d'une lecture
          </span>
        </div>
      )}
    </Card>
  );
}

// Budget & RTK : plan fournisseur MiMo, puis quotas du tenant par ressource, puis économie RTK.
export function Budget() {
  const token = useToken();
  const quota = usePoll(() => api.getQuota(token), 4000);
  const metrics = usePoll(() => api.getMetrics(token), 4000);
  const mimo = usePoll(() => api.getMimoBudget(token), 10000);

  const resources = pairResources(quota.data);

  return (
    <>
      <ViewHeader title="budget & rtk" />

      {mimo.data && <MimoPlan b={mimo.data} />}
      {mimo.error != null && !mimo.data && (
        <Card style={{ marginBottom: "var(--space-6)", fontSize: "13px", color: "var(--text-muted)" }}>
          plan mimo indisponible — le solde fournisseur n'est pas lisible depuis cette instance.
        </Card>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "var(--space-4)", marginBottom: "var(--space-6)" }}>
        <MetricCard label="économie rtk" value={Math.round(metrics.data?.savings_pct ?? 0)} unit="%" mono deltaTone="teal" />
        <MetricCard label="coût cumulé" value={`${(metrics.data?.cost ?? 0).toFixed(3)} $`} mono />
      </div>

      <Card style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
        {quota.loading && (
          <div style={{ color: "var(--text-muted)", fontSize: "13px" }}>lecture des quotas…</div>
        )}
        {quota.error != null && !quota.loading && resources.length === 0 && (
          <div style={{ color: "var(--text-muted)", fontSize: "13px" }}>
            quotas indisponibles — vérifiez que le tenant a des limites définies.
          </div>
        )}
        {resources.map(([key, r]) => {
          const pct = r.limit > 0 ? (r.used / r.limit) * 100 : 0;
          return (
            <div key={key} style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "13px" }}>
                <span style={{ color: "var(--text-secondary)" }}>{LABELS[key] ?? key}</span>
                <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
                  {Math.round(r.used).toLocaleString()} / {Math.round(r.limit).toLocaleString()}
                </span>
              </div>
              <ProgressBar value={pct} max={100} height={8} />
            </div>
          );
        })}
      </Card>
    </>
  );
}
