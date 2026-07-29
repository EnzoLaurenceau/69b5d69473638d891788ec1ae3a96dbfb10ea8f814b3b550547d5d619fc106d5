import React from "react";

/**
 * Status badge. Colour = meaning. Default is the light-fill pill (50 bg / 900 text);
 * `solid` uses the 900 fill / 50 text. `pulse` adds the one tolerated micro-animation
 * for a live "active" state (wrapped in prefers-reduced-motion).
 */
export function StatusBadge({ status = "idle", solid = false, pulse = false, children, style, ...rest }) {
  const map = {
    active: { bg: "var(--forge-teal-50)", fg: "var(--forge-teal-900)", solidBg: "var(--forge-teal-900)", dot: "var(--forge-teal-400)" },
    idle:   { bg: "var(--forge-gray-50)", fg: "var(--forge-gray-900)", solidBg: "var(--forge-gray-900)", dot: "var(--forge-gray-400)" },
    warn:   { bg: "var(--forge-amber-50)", fg: "var(--forge-amber-900)", solidBg: "var(--forge-amber-900)", dot: "var(--forge-amber-400)" },
    error:  { bg: "var(--forge-coral-50)", fg: "var(--forge-coral-900)", solidBg: "var(--forge-coral-900)", dot: "var(--forge-coral-400)" },
    info:   { bg: "var(--forge-blue-50)", fg: "var(--forge-blue-900)", solidBg: "var(--forge-blue-900)", dot: "var(--forge-blue-400)" },
  };
  const c = map[status] || map.idle;
  return (
    <span
      style={{
        display: "inline-flex", alignItems: "center", gap: "6px",
        fontFamily: "var(--font-ui)", fontSize: "11px", fontWeight: 500, lineHeight: 1,
        padding: "3px 9px", borderRadius: "var(--radius-md)",
        background: solid ? c.solidBg : c.bg,
        color: solid ? c.bg : c.fg,
        ...style,
      }}
      {...rest}
    >
      <span
        className={pulse ? "forge-pulse" : undefined}
        style={{ width: 6, height: 6, borderRadius: "50%", background: c.dot, flex: "0 0 auto" }}
      />
      {children}
      {pulse && (
        <style>{`@media (prefers-reduced-motion: no-preference){.forge-pulse{animation:forgePulse 1.6s ease-in-out infinite}@keyframes forgePulse{0%,100%{opacity:1}50%{opacity:.35}}}`}</style>
      )}
    </span>
  );
}
