import { Card, MetricCard, StatusBadge } from "../design-system";
import { ViewHeader } from "../components/Shell";
import { usePoll } from "../components/usePoll";
import { api } from "../api/client";
import type { RunStatus } from "../api/types";
import { useToken } from "../auth/AuthContext";

const STATUS_MAP: Record<RunStatus, { badge: "active" | "idle" | "error" | "info"; label: string }> = {
  queued: { badge: "idle", label: "en file" },
  running: { badge: "active", label: "en cours" },
  done: { badge: "info", label: "terminé" },
  error: { badge: "error", label: "erreur" },
  cancelled: { badge: "idle", label: "annulé" },
  cancelling: { badge: "idle", label: "annulation" },
};

function money(n: number) {
  return `${(n || 0).toFixed(3)} $`;
}

// Tableau de bord : chiffres RÉELS issus de /v1 (metrics + quota + agents + runs). Aucun mock.
export function Dashboard() {
  const token = useToken();
  const metrics = usePoll(() => api.getMetrics(token), 4000);
  const agents = usePoll(() => api.getAgents(token), 8000);
  const runs = usePoll(() => api.listRuns(token, 8), 3000);

  const m = metrics.data;
  const agentCount = agents.data?.agents.length ?? 0;

  return (
    <>
      <ViewHeader title="tableau de bord" />
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "var(--space-4)",
        marginBottom: "var(--space-6)",
      }}>
        <MetricCard label="agents disponibles" value={agentCount} mono />
        <MetricCard label="tokens (in / out)" value={`${m?.tokens_in ?? 0} / ${m?.tokens_out ?? 0}`} mono />
        <MetricCard label="coût session" value={money(m?.cost ?? 0)} mono />
        <MetricCard label="économie rtk" value={`${Math.round(m?.savings_pct ?? 0)}`} unit="%" delta="rtk" deltaTone="teal" mono />
      </div>

      <Card padded={false}>
        <div style={{ padding: "12px 20px", borderBottom: "0.5px solid var(--border)", fontSize: "13px", color: "var(--text-secondary)" }}>
          runs récents
        </div>
        {runs.loading && (
          <div style={{ padding: "16px 20px" }}>
            {[0, 1, 2].map((i) => (
              <div key={i} style={{ height: 14, background: "var(--surface-2)", borderRadius: 6, margin: "8px 0", opacity: 0.6 }} />
            ))}
          </div>
        )}
        {!runs.loading && (runs.data?.runs.length ?? 0) === 0 && (
          <div style={{ padding: "20px", color: "var(--text-muted)", fontSize: "14px" }}>
            aucun run pour l'instant — lancez votre premier agent depuis l'orchestrateur.
          </div>
        )}
        {runs.data?.runs.map((r) => {
          const s = STATUS_MAP[r.status] ?? { badge: "idle" as const, label: r.status };
          return (
            <div key={r.run_id} style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "12px 20px", borderBottom: "0.5px solid var(--border)",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", minWidth: 0 }}>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--text-muted)" }}>
                  {r.run_id.slice(0, 10)}
                </span>
                <span style={{ fontSize: "14px", color: "var(--text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {r.task}
                </span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "var(--space-4)" }}>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--text-secondary)" }}>
                  {money(r.cost)}
                </span>
                <StatusBadge status={s.badge} pulse={r.status === "running"}>{s.label}</StatusBadge>
              </div>
            </div>
          );
        })}
      </Card>
    </>
  );
}
