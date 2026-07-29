import { Card, Icon, StatusBadge } from "../design-system";
import { ViewHeader } from "../components/Shell";
import { usePoll } from "../components/usePoll";
import { api } from "../api/client";
import { useToken } from "../auth/AuthContext";
import type { RouterTier } from "../api/types";

// Couleur = signification. Payant en ambre : c'est ce qui coûte, ça doit sauter aux yeux.
const BADGE: Record<RouterTier["kind"], { status: "info" | "warn" | "idle"; label: string }> = {
  subscription: { status: "info", label: "abonnement" },
  paid: { status: "warn", label: "payant" },
  removed: { status: "idle", label: "retiré" },
};

export function Router() {
  const token = useToken();
  const tiers = usePoll(() => api.getRouterTiers(token), 10000);
  const data = tiers.data;
  const noFree = data ? data.free_tier_available === false : false;

  return (
    <>
      <ViewHeader title="router llm" />

      <Card style={{ marginBottom: "var(--space-4)", display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
        <Icon name="route" size={18} color="var(--forge-blue-400)" />
        <span style={{ fontSize: "14px", color: "var(--text-secondary)" }}>
          politique par défaut :{" "}
          <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-primary)" }}>
            {data?.default_policy ?? "—"}
          </span>
        </span>
      </Card>

      {/* Sans destination gratuite, tout volume déchargé est facturé. Le dire ici évite
          de router du volume « pour économiser » vers quelque chose qui coûte. */}
      {noFree && (
        <Card style={{ marginBottom: "var(--space-4)", display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
          <Icon name="alert-triangle" size={18} color="var(--forge-amber-400)" />
          <span style={{ fontSize: "14px", color: "var(--text-secondary)" }}>
            aucun tier gratuit — <span style={{ color: "var(--text-primary)" }}>chaque token déchargé est facturé</span>
          </span>
        </Card>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "var(--space-4)" }}>
        {(data?.tiers ?? []).map((t) => {
          const badge = BADGE[t.kind] ?? BADGE.removed;
          const gone = t.kind === "removed";
          // Une branche encore dans le code, avec une clé configurée, alors qu'on l'a
          // abandonnée : ça peut encore s'exécuter. C'est le seul cas qui mérite une alerte.
          const zombie = gone && t.wired && t.available;
          return (
            <Card
              key={t.name}
              style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)", opacity: gone ? 0.55 : 1 }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{ fontSize: "var(--text-h3)", fontWeight: 500 }}>{t.name.toLowerCase()}</span>
                <StatusBadge status={badge.status}>{badge.label}</StatusBadge>
              </div>

              <span style={{ fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--text-muted)", lineHeight: 1.5 }}>
                {t.detail}
              </span>

              {!gone && !t.available && (
                <StatusBadge status="warn">clé absente</StatusBadge>
              )}
              {zombie && (
                <StatusBadge status="error">clé encore active</StatusBadge>
              )}
            </Card>
          );
        })}

        {tiers.loading && [0, 1, 2].map((i) => (
          <div key={i} style={{ height: 96, background: "var(--surface-2)", borderRadius: "var(--radius-lg)", opacity: 0.5 }} />
        ))}
      </div>
    </>
  );
}
