import React from "react";

/**
 * Icon wrapper over the Tabler outline set (ti ti-{name}). Outline only, never -filled.
 * Requires the Tabler icons stylesheet to be linked on the page.
 */
export function Icon({ name, size = 18, color = "currentColor", style, ...rest }) {
  return (
    <i
      className={`ti ti-${name}`}
      style={{ fontSize: `${size}px`, color, lineHeight: 1, display: "inline-flex", ...style }}
      {...rest}
    />
  );
}
