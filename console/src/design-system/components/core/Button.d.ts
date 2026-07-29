import React from "react";

export interface ButtonProps {
  /** Visual weight. primary = coral CTA, secondary = filled neutral, ghost = outline. */
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md";
  /** Tabler outline icon name (without the `ti-` prefix), rendered before the label. */
  icon?: string;
  /** Tabler outline icon name, rendered after the label. */
  iconRight?: string;
  disabled?: boolean;
  type?: "button" | "submit" | "reset";
  onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void;
  style?: React.CSSProperties;
  children?: React.ReactNode;
}

/**
 * Button — La Forge action control. Coral primary used with restraint.
 * @startingPoint section="Core" subtitle="Primary / secondary / ghost actions" viewport="360x120"
 */
export function Button(props: ButtonProps): JSX.Element;
