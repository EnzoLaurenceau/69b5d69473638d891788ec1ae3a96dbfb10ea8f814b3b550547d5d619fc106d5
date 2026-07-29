import React from "react";
import { Icon } from "../design-system";
import { useAuth } from "../auth/AuthContext";

export type ViewKey = "dashboard" | "orchestrator" | "router" | "budget" | "map" | "kanban";

const NAV: { key: ViewKey; label: string; icon: string }[] = [
  { key: "dashboard", label: "tableau de bord", icon: "layout-dashboard" },
  { key: "kanban", label: "backlog rpg", icon: "kanban-square" },
  { key: "orchestrator", label: "orchestrateur", icon: "git-branch" },
  { key: "router", label: "router llm", icon: "network" },
  { key: "budget", label: "budget & rtk", icon: "battery-2" },
  { key: "map", label: "neural map", icon: "cpu" },
];

// Layout : sidebar fixe + zone principale. Dark-first, surfaces plates (design-system.md).
export function Shell({ view, onNavigate, children }: {
  view: ViewKey;
  onNavigate: (v: ViewKey) => void;
  children: React.ReactNode;
}) {
  const { setToken } = useAuth();
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "220px 1fr", minHeight: "100vh",
      background: "var(--bg)", color: "var(--text-primary)", fontFamily: "var(--font-ui)",
    }}>
      <aside style={{
        borderRight: "0.5px solid var(--border)", padding: "var(--space-6) var(--space-4)",
        display: "flex", flexDirection: "column", gap: "var(--space-2)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", marginBottom: "var(--space-6)", paddingLeft: "var(--space-2)" }}>
          <Icon name="flame" size={20} color="var(--accent)" />
          <span style={{ fontSize: "var(--text-h3)", fontWeight: 500 }}>la forge</span>
        </div>
        {NAV.map((n) => {
          const active = n.key === view;
          return (
            <button
              key={n.key}
              onClick={() => onNavigate(n.key)}
              style={{
                display: "flex", alignItems: "center", gap: "var(--space-3)",
                padding: "9px 12px", borderRadius: "var(--radius-md)",
                border: "0.5px solid transparent", cursor: "pointer", textAlign: "left",
                fontFamily: "var(--font-ui)", fontSize: "14px", fontWeight: active ? 500 : 400,
                background: active ? "var(--surface)" : "transparent",
                color: active ? "var(--text-primary)" : "var(--text-secondary)",
              }}
            >
              <Icon name={n.icon} size={17} color={active ? "var(--accent)" : "var(--text-muted)"} />
              {n.label}
            </button>
          );
        })}
        <div style={{ marginTop: "auto" }}>
          <button
            onClick={() => setToken(null)}
            style={{
              display: "flex", alignItems: "center", gap: "var(--space-3)", width: "100%",
              padding: "9px 12px", borderRadius: "var(--radius-md)", border: "0.5px solid transparent",
              cursor: "pointer", textAlign: "left", background: "transparent",
              fontFamily: "var(--font-ui)", fontSize: "13px", color: "var(--text-muted)",
            }}
          >
            <Icon name="logout" size={16} color="var(--text-muted)" />
            fermer la session
          </button>
        </div>
      </aside>
      <main style={{ padding: "var(--space-8)", overflow: "auto" }}>{children}</main>
    </div>
  );
}

// En-tête de vue réutilisable : titre en casse phrase, sans title case (règle typo).
export function ViewHeader({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      marginBottom: "var(--space-6)",
    }}>
      <h1 style={{ fontSize: "var(--text-h1)", fontWeight: 500, margin: 0 }}>{title}</h1>
      {action}
    </div>
  );
}
