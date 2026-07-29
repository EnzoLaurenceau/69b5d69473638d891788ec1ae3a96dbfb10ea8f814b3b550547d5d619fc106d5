import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ViewHeader } from "../components/Shell";
import type { BacklogData, BacklogTask } from "../api/types";

/** Colonnes kanban — alignées sur TASK_STATES de forge_backlog.py */
const COLUMNS: { key: string; label: string; color: string }[] = [
  { key: "pending",     label: "en attente",       color: "var(--text-muted)" },
  { key: "ready",       label: "prêt",             color: "#3b82f6" },
  { key: "in_progress", label: "en cours",         color: "#f59e0b" },
  { key: "blocked",     label: "bloqué",           color: "#ef4444" },
  { key: "done",        label: "terminé",          color: "#22c55e" },
];

const COMPLEXITY_COLOR: Record<string, string> = {
  S: "#22c55e",
  M: "#f59e0b",
  H: "#ef4444",
};

function TaskCard({ task, schedule }: {
  task: BacklogTask;
  schedule: BacklogData["critical_path"]["schedule"];
}) {
  const slack = schedule[task.id]?.slack;
  const isCritical = slack !== undefined && slack <= 0.001;
  return (
    <div style={{
      background: "var(--surface)",
      border: `0.5px solid ${isCritical ? "var(--accent)" : "var(--border)"}`,
      borderRadius: "var(--radius-md)",
      padding: "12px",
      display: "flex",
      flexDirection: "column",
      gap: "6px",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <span style={{
          fontSize: "11px", fontWeight: 600, fontFamily: "var(--font-mono)",
          color: "var(--accent)", minWidth: "52px",
        }}>{task.id}</span>
        <span style={{
          fontSize: "10px", padding: "1px 6px", borderRadius: "4px",
          background: `${COMPLEXITY_COLOR[task.complexity] || "#888"}22`,
          color: COMPLEXITY_COLOR[task.complexity] || "#888",
          fontWeight: 600,
        }}>{task.complexity}</span>
        {isCritical && (
          <span style={{
            fontSize: "9px", padding: "1px 5px", borderRadius: "4px",
            background: "var(--accent)22", color: "var(--accent)", fontWeight: 600,
          }}>CP</span>
        )}
        {task.retries > 0 && (
          <span style={{
            fontSize: "9px", padding: "1px 5px", borderRadius: "4px",
            background: "#ef444422", color: "#ef4444", fontWeight: 600,
          }}>↻{task.retries}</span>
        )}
      </div>
      <div style={{ fontSize: "13px", lineHeight: 1.4 }}>{task.title}</div>
      <div style={{
        display: "flex", alignItems: "center", gap: "10px",
        fontSize: "11px", color: "var(--text-muted)",
      }}>
        <span>{task.epic}</span>
        {task.effort_days > 0 && <span>{task.effort_days}j</span>}
        {task.depends_on.length > 0 && (
          <span title={task.depends_on.join(", ")}>→ {task.depends_on.length} dep</span>
        )}
      </div>
      {task.block_reason && (
        <div style={{
          fontSize: "11px", color: "#ef4444", fontStyle: "italic",
          borderTop: "0.5px solid var(--border)", paddingTop: "6px",
        }}>🚫 {task.block_reason}</div>
      )}
    </div>
  );
}

export function Kanban() {
  const { token } = useAuth();
  const [data, setData] = useState<BacklogData | null>(null);
  const [error, setError] = useState("");
  const [filterEpic, setFilterEpic] = useState<string>("");

  useEffect(() => {
    if (!token) return;
    api.getBacklog(token).then(setData).catch((e) => setError(String(e)));
  }, [token]);

  if (error) return <div style={{ color: "#ef4444" }}>Erreur : {error}</div>;
  if (!data) return <div style={{ color: "var(--text-muted)" }}>Chargement…</div>;

  const epics = Object.keys(data.epic_summary).sort();
  const tasks = filterEpic
    ? data.tasks.filter((t) => t.epic === filterEpic)
    : data.tasks;

  const tasksByState = COLUMNS.reduce<Record<string, BacklogTask[]>>((acc, col) => {
    acc[col.key] = tasks.filter((t) => t.state === col.key);
    return acc;
  }, {});

  const schedule = data.critical_path?.schedule || {};

  return (
    <div>
      <ViewHeader
        title="backlog rpg"
        action={
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <select
              value={filterEpic}
              onChange={(e) => setFilterEpic(e.target.value)}
              style={{
                background: "var(--surface)", color: "var(--text-primary)",
                border: "0.5px solid var(--border)", borderRadius: "var(--radius-md)",
                padding: "6px 10px", fontSize: "13px", cursor: "pointer",
              }}
            >
              <option value="">tous les epics</option>
              {epics.map((e) => (
                <option key={e} value={e}>
                  {e} ({data.epic_summary[e].done}/{data.epic_summary[e].tasks})
                </option>
              ))}
            </select>
          </div>
        }
      />

      {/* Résumé */}
      <div style={{
        display: "flex", gap: "16px", marginBottom: "var(--space-6)",
        fontSize: "13px", color: "var(--text-secondary)",
      }}>
        <span>{data.summary.tasks} tâches</span>
        <span>{data.summary.by_state["done"] || 0} terminées</span>
        <span>{data.summary.ready.length} prêtes</span>
        <span>chemin critique : {data.critical_path.duration_days.toFixed(0)}j</span>
        {data.summary.cycles.length > 0 && (
          <span style={{ color: "#ef4444" }}>
            ⚠️ {data.summary.cycles.length} cycle(s)
          </span>
        )}
      </div>

      {/* Épic summary bar */}
      <div style={{
        display: "flex", gap: "8px", marginBottom: "var(--space-6)", flexWrap: "wrap",
      }}>
        {epics.map((e) => {
          const es = data.epic_summary[e];
          const pct = es.pct_done;
          return (
            <div
              key={e}
              onClick={() => setFilterEpic(filterEpic === e ? "" : e)}
              style={{
                cursor: "pointer",
                background: filterEpic === e ? "var(--accent)22" : "var(--surface)",
                border: `0.5px solid ${filterEpic === e ? "var(--accent)" : "var(--border)"}`,
                borderRadius: "var(--radius-md)",
                padding: "6px 12px",
                display: "flex", alignItems: "center", gap: "8px",
                fontSize: "12px",
              }}
            >
              <span style={{ fontWeight: 600 }}>{e}</span>
              <span style={{
                width: "40px", height: "4px", borderRadius: "2px",
                background: "var(--border)", overflow: "hidden",
              }}>
                <span style={{
                  display: "block", height: "100%",
                  width: `${pct}%`,
                  background: pct === 100 ? "#22c55e" : "var(--accent)",
                  borderRadius: "2px",
                }} />
              </span>
              <span style={{ color: "var(--text-muted)" }}>
                {es.done}/{es.tasks}
              </span>
            </div>
          );
        })}
      </div>

      {/* Board */}
      <div style={{
        display: "grid",
        gridTemplateColumns: `repeat(${COLUMNS.length}, 1fr)`,
        gap: "12px",
        alignItems: "start",
      }}>
        {COLUMNS.map((col) => (
          <div key={col.key}>
            <div style={{
              display: "flex", alignItems: "center", gap: "8px",
              marginBottom: "12px", paddingBottom: "8px",
              borderBottom: `2px solid ${col.color}`,
            }}>
              <span style={{
                fontSize: "13px", fontWeight: 600,
                color: col.color,
              }}>{col.label}</span>
              <span style={{
                fontSize: "11px", color: "var(--text-muted)",
              }}>({tasksByState[col.key]?.length || 0})</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {tasksByState[col.key]?.map((task) => (
                <TaskCard key={task.id} task={task} schedule={schedule} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
