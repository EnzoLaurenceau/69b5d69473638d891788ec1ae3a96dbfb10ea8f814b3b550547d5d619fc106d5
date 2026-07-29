import React from "react";

export interface MetricCardProps {
  /** Muted 13px label above the value. */
  label: string;
  /** The metric value (number or preformatted string). */
  value: React.ReactNode;
  /** Optional trailing unit, e.g. "%", "ms", "$". */
  unit?: string;
  /** Optional trend delta, e.g. "-23%" or "+6". */
  delta?: string;
  deltaTone?: "teal" | "coral" | "amber" | "blue" | "gray";
  /** Render the value in the mono font (for tokens / costs / ids). */
  mono?: boolean;
  style?: React.CSSProperties;
}

/**
 * MetricCard — dashboard KPI tile. Label 13px muted, value 24px/500, no border.
 * @startingPoint section="Core" subtitle="Dashboard KPI tile" viewport="260x110"
 */
export function MetricCard(props: MetricCardProps): JSX.Element;
