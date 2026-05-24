/**
 * @file StatusPill.tsx
 * @description Reusable presentational component for rendering execution status tags
 * in the AI Co-Computational Physicist Factory. Displays compact, rectangular elements
 * with 2px rounded corners and specific color schemes per status, avoiding generic pill styling.
 *
 * Use Cases:
 * - Rendered in data tables to summarize execution outcomes (G2 worthiness, G4 validation, etc.).
 * - Embedded inside the PipelineVisual nodes to show gate state.
 * - Used in sidebars or detail pages to track human triage decisions (G6 queue).
 */

import React from 'react';
import { THEME, logUIAction } from './theme';

// Normalize types to avoid duplicate mapping code in other modules
export type StatusType =
  | 'passed'
  | 'pass'
  | 'failed'
  | 'fail'
  | 'pending'
  | 'running'
  | 'in-progress'
  | 'dissent'
  | 'qualified'
  | 'parked';

export interface StatusPillProps {
  /** The execution state to render */
  status: StatusType;
  /** Optional custom text label override; defaults to capitalization of status name */
  label?: string;
  /** Standard CSS classes for custom container adjustments */
  className?: string;
  /** Triggered when the user clicks the pill, supporting interactive lists */
  onClick?: (event: React.MouseEvent<HTMLSpanElement>) => void;
  /** Inline style overrides */
  style?: React.CSSProperties;
}

/**
 * Normalizes input status aliases to unified system status categories.
 * @param status Raw status input string
 * @returns Normalized system status
 */
function normalizeStatus(status: StatusType): 'passed' | 'failed' | 'pending' | 'running' | 'dissent' | 'qualified' | 'parked' {
  switch (status) {
    case 'pass':
      return 'passed';
    case 'fail':
      return 'failed';
    case 'in-progress':
      return 'running';
    default:
      return status;
  }
}

/**
 * StatusPill displays execution states using curated operations-console styling.
 * Features a rectangular 2px corner radius, strict type-safety, and inline styling fallback.
 */
export const StatusPill: React.FC<StatusPillProps> = ({
  status,
  label,
  className = '',
  onClick,
  style,
}) => {
  const normStatus = normalizeStatus(status);

  // Retrieve design tokens based on status
  const color = THEME.colors.status[normStatus];
  const backgroundColor = THEME.colors.alpha[normStatus];
  const border = normStatus === 'qualified'
    ? `1px solid ${THEME.colors.status.qualified}`
    : `1px solid ${color}4D`; // 30% opacity border for others

  // Prepare standard display text
  const displayText = label || (normStatus === 'running' ? 'running' : normStatus);

  // Render wrapper with inline style fallback for environments without CSS modules
  const pillStyle: React.CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontFamily: THEME.fonts.mono,
    fontSize: '11px',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    padding: '3px 7px',
    borderRadius: THEME.radius.pill,
    color: color,
    backgroundColor: backgroundColor,
    border: border,
    cursor: onClick ? 'pointer' : 'default',
    userSelect: 'none',
    transition: 'all 0.15s ease-in-out',
    ...style,
  };

  const handlePillClick = (e: React.MouseEvent<HTMLSpanElement>) => {
    logUIAction('StatusPill', 'onClick', { status, normStatus, label: displayText });
    if (onClick) {
      onClick(e);
    }
  };

  return (
    <span
      className={`status-pill status-${normStatus} ${className}`}
      style={pillStyle}
      onClick={handlePillClick}
    >
      {displayText}
    </span>
  );
};
