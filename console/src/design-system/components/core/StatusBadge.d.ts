import React from "react";

export interface StatusBadgeProps {
  /** Semantic state. Drives colour: active=teal, idle=gray, warn=amber, error=coral, info=blue. */
  status?: "active" | "idle" | "warn" | "error" | "info";
  /** Use the 900 solid fill instead of the light-fill pill. */
  solid?: boolean;
  /** Micro-pulse the status dot (only for a live "active"/"en cours" state). */
  pulse?: boolean;
  children?: React.ReactNode;
  style?: React.CSSProperties;
}

/**
 * StatusBadge — small pill whose colour encodes agent/task state.
 * @startingPoint section="Core" subtitle="Semantic status pill" viewport="360x80"
 */
export function StatusBadge(props: StatusBadgeProps): JSX.Element;
