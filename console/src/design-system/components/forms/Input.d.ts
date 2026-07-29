import React from "react";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  /** Optional leading Tabler outline icon name (without `ti-`). */
  icon?: string;
  /** Use the mono font (for ids, paths, token values). */
  mono?: boolean;
  disabled?: boolean;
  style?: React.CSSProperties;
}

/**
 * Input — single-line text field. Flat, hairline border, coral focus ring.
 * @startingPoint section="Forms" subtitle="Text field with focus ring" viewport="360x80"
 */
export function Input(props: InputProps): JSX.Element;
