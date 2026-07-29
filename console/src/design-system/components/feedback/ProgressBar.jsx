import React from "react";

/**
 * Flat progress / budget bar. Track + fill, no gradient. Colour carries meaning
 * (teal ok, amber watch, coral over). Auto-tones by value if `tone` omitted.
 */
export function ProgressBar({ value = 0, max = 100, tone, height = 6, showLabel = false, style, ...rest }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const auto = pct >= 90 ? "coral" : pct >= 70 ? "amber" : "teal";
  const t = tone || auto;
  const colors = {
    teal: "var(--forge-teal-400)",
    amber: "var(--forge-amber-400)",
    coral: "var(--forge-coral-400)",
    blue: "var(--forge-blue-400)",
    gray: "var(--forge-gray-400)",
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "6px", ...style }} {...rest}>
      {showLabel && (
        <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--text-secondary)" }}>
          <span>{Math.round(pct)}%</span>
          <span>{value} / {max}</span>
        </div>
      )}
      <div style={{ height: `${height}px`, background: "var(--surface-2)", borderRadius: "999px", overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: colors[t], borderRadius: "999px", transition: "width .4s ease" }} />
      </div>
    </div>
  );
}
