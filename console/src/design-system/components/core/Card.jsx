import React from "react";

/** Standard La Forge card: flat surface, 0.5px hairline border, radius-lg. */
export function Card({ padded = true, style, children, ...rest }) {
  return (
    <div
      style={{
        background: "var(--surface)",
        border: "0.5px solid var(--border)",
        borderRadius: "var(--radius-lg)",
        padding: padded ? "16px 20px" : 0,
        fontFamily: "var(--font-ui)",
        color: "var(--text-primary)",
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}
