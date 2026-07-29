import React from "react";

/**
 * Metric card for dashboards: muted 13px label on top, 24px/500 value below.
 * No border, flat surface. Optional mono value + trend delta.
 */
export function MetricCard({ label, value, unit, delta, deltaTone = "teal", mono = false, style, ...rest }) {
  const tones = {
    teal: "var(--forge-teal-400)",
    coral: "var(--forge-coral-400)",
    amber: "var(--forge-amber-400)",
    blue: "var(--forge-blue-400)",
    gray: "var(--text-muted)",
  };
  return (
    <div
      style={{
        background: "var(--surface)",
        borderRadius: "var(--radius-lg)",
        padding: "16px 20px",
        fontFamily: "var(--font-ui)",
        display: "flex",
        flexDirection: "column",
        gap: "6px",
        ...style,
      }}
      {...rest}
    >
      <span style={{ fontSize: "13px", color: "var(--text-secondary)", fontWeight: 400 }}>{label}</span>
      <div style={{ display: "flex", alignItems: "baseline", gap: "8px" }}>
        <span style={{
          fontSize: "24px", fontWeight: 500, color: "var(--text-primary)", lineHeight: 1,
          fontFamily: mono ? "var(--font-mono)" : "var(--font-ui)",
          fontVariantNumeric: "tabular-nums",
        }}>
          {value}{unit && <span style={{ fontSize: "14px", color: "var(--text-muted)", marginLeft: 2 }}>{unit}</span>}
        </span>
        {delta != null && (
          <span style={{ fontSize: "12px", fontWeight: 500, color: tones[deltaTone], fontFamily: "var(--font-mono)" }}>
            {delta}
          </span>
        )}
      </div>
    </div>
  );
}
