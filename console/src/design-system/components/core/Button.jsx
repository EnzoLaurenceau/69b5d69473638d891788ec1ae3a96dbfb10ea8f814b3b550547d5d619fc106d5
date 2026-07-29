import React from "react";

/**
 * Primary CTA uses coral. No gradients, no glow. Hover darkens ~10%,
 * active scales to 0.98. Sentence case labels only.
 */
export function Button({
  variant = "primary",
  size = "md",
  icon,
  iconRight,
  disabled = false,
  type = "button",
  onClick,
  style,
  children,
  ...rest
}) {
  const sizes = {
    sm: { padding: "6px 12px", fontSize: "13px", gap: "6px" },
    md: { padding: "9px 16px", fontSize: "14px", gap: "8px" },
  };
  const variants = {
    primary: {
      background: "var(--accent)",
      color: "var(--text-on-accent)",
      border: "0.5px solid transparent",
    },
    secondary: {
      background: "var(--surface-2)",
      color: "var(--text-primary)",
      border: "0.5px solid var(--border-strong)",
    },
    ghost: {
      background: "transparent",
      color: "var(--text-secondary)",
      border: "0.5px solid var(--border)",
    },
  };
  const base = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    ...sizes[size],
    ...variants[variant],
    fontFamily: "var(--font-ui)",
    fontWeight: 500,
    lineHeight: 1,
    borderRadius: "var(--radius-md)",
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.45 : 1,
    transition: "background .15s ease, transform .05s ease, filter .15s ease",
    whiteSpace: "nowrap",
    ...style,
  };
  const onDown = (e) => { if (!disabled) e.currentTarget.style.transform = "scale(0.98)"; };
  const onUp = (e) => { e.currentTarget.style.transform = "scale(1)"; };
  const onEnter = (e) => {
    if (disabled) return;
    if (variant === "primary") e.currentTarget.style.background = "var(--accent-hover)";
    else e.currentTarget.style.background = "var(--surface)";
  };
  const onLeave = (e) => {
    e.currentTarget.style.transform = "scale(1)";
    e.currentTarget.style.background = variants[variant].background;
  };
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      style={base}
      onMouseDown={onDown}
      onMouseUp={onUp}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      {...rest}
    >
      {icon && <i className={`ti ti-${icon}`} style={{ fontSize: "1.1em" }} />}
      {children}
      {iconRight && <i className={`ti ti-${iconRight}`} style={{ fontSize: "1.1em" }} />}
    </button>
  );
}
