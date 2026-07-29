import React from "react";

export interface IconProps {
  /** Tabler icon name without the `ti-` prefix, e.g. "flame", "cpu", "network". */
  name: string;
  /** Pixel size (square). Default 18. */
  size?: number;
  color?: string;
  style?: React.CSSProperties;
}

/**
 * Icon — wrapper over Tabler outline glyphs. Outline only, never -filled, never emoji.
 * Requires the Tabler icons CSS on the page (see prompt).
 */
export function Icon(props: IconProps): JSX.Element;
