import React from "react";

export interface CardProps {
  /** Apply default 1rem 1.25rem padding. Set false for flush content (tables, media). */
  padded?: boolean;
  style?: React.CSSProperties;
  children?: React.ReactNode;
}

/**
 * Card — standard flat container. surface-dark, 0.5px hairline border, radius-lg.
 * @startingPoint section="Core" subtitle="Flat container with hairline border" viewport="360x160"
 */
export function Card(props: CardProps): JSX.Element;
