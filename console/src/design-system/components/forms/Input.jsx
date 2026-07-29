import React from "react";

/** Text input. Flat surface, 0.5px border, radius-md. Focus ring uses coral accent. */
export function Input({ icon, mono = false, disabled = false, style, ...rest }) {
  const [focus, setFocus] = React.useState(false);
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: "8px",
      background: "var(--bg)",
      border: `0.5px solid ${focus ? "var(--accent)" : "var(--border-strong)"}`,
      borderRadius: "var(--radius-md)",
      padding: "0 12px", height: "38px",
      opacity: disabled ? 0.5 : 1,
      transition: "border-color .15s ease",
      ...style,
    }}>
      {icon && <i className={`ti ti-${icon}`} style={{ color: "var(--text-muted)", fontSize: "16px" }} />}
      <input
        disabled={disabled}
        onFocus={() => setFocus(true)}
        onBlur={() => setFocus(false)}
        style={{
          flex: 1, background: "transparent", border: "none", outline: "none",
          color: "var(--text-primary)", fontSize: "14px",
          fontFamily: mono ? "var(--font-mono)" : "var(--font-ui)",
        }}
        {...rest}
      />
    </div>
  );
}
