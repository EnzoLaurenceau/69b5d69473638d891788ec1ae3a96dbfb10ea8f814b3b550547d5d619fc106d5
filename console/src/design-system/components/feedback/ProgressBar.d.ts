import React from "react";

export interface ProgressBarProps {
  value?: number;
  max?: number;
  /** Semantic colour. Omit to auto-tone: teal <70%, amber 70-90%, coral >=90%. */
  tone?: "teal" | "amber" | "coral" | "blue" | "gray";
  /** Track height in px. Default 6. */
  height?: number;
  /** Show percentage + value/max caption above the track. */
  showLabel?: boolean;
  style?: React.CSSProperties;
}

/**
 * ProgressBar — flat budget / quota / efficiency bar. Colour encodes headroom.
 * @startingPoint section="Feedback" subtitle="Budget / quota bar" viewport="360x80"
 */
export function ProgressBar(props: ProgressBarProps): JSX.Element;
