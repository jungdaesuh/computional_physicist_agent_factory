/**
 * @file PipelineVisual.tsx
 * @description Horizontal 9-gate tracker visualization for candidate hypotheses.
 * Renders the state machine path from G0 (Domain) to G6 (Human approval) with status-aware
 * connecting lines, active gate highlight, and compact status pills inside.
 *
 * Use Cases:
 * - Main layout element in the Gate Pipeline View to monitor runtime progression.
 * - Header element in Hypothesis Detail page to provide instant visual index of cycle history.
 */

import React from 'react';
import { THEME, logUIAction } from './theme';
import { StatusPill, StatusType } from './StatusPill';

export interface GateInfo {
  /** Short identifier, e.g., 'G0', 'G1', 'G1.5', 'G2', 'G2.5', 'G3', 'G4', 'G5', 'G6' */
  id: string;
  /** Primary label displayed below the gate node (e.g., 'Domain') */
  label: string;
  /** Current execution status of this specific gate */
  status: StatusType;
}

export interface PipelineVisualProps {
  /** The currently running gate identifier to highlight (e.g., 'G3') */
  activeGateId: string;
  /** Explicit array of 9 gates. Defaults to standard state machine if omitted. */
  gates?: GateInfo[];
  /** Callback fired when the user selects a gate to view its logs/artifacts */
  onGateSelect?: (gateId: string) => void;
  /** Custom class names for layout wrapper */
  className?: string;
}

// Standard 9 gates defined in the research factory state machine
const DEFAULT_GATES: GateInfo[] = [
  { id: 'G0', label: 'Domain', status: 'pending' },
  { id: 'G1', label: 'Falsifiability', status: 'pending' },
  { id: 'G1.5', label: 'Simulability', status: 'pending' },
  { id: 'G2', label: 'Worthiness', status: 'pending' },
  { id: 'G2.5', label: 'Tractability', status: 'pending' },
  { id: 'G3', label: 'Surrogate', status: 'pending' },
  { id: 'G4', label: 'Validation', status: 'pending' },
  { id: 'G5', label: 'Interpretation', status: 'pending' },
  { id: 'G6', label: 'Human', status: 'pending' },
];

/**
 * PipelineVisual renders a horizontal pipeline representing the 9 evaluation gates.
 * Handles responsive layout, active gate elevation, left accent cyan highlight, and status-colored connectors.
 */
export const PipelineVisual: React.FC<PipelineVisualProps> = ({
  activeGateId,
  gates = DEFAULT_GATES,
  onGateSelect,
  className = '',
}) => {
  const handleGateClick = (gateId: string) => {
    logUIAction('PipelineVisual', 'onGateSelect', { gateId, activeGateId });
    if (onGateSelect) {
      onGateSelect(gateId);
    }
  };

  // Helper to determine connecting line color between gate A and gate B
  const getConnectorStyle = (index: number): React.CSSProperties => {
    const current = gates[index];
    const next = gates[index + 1];
    
    let color = '#1C1C20'; // default line color
    if (current && next) {
      if (current.status === 'passed') {
        color = THEME.colors.status.passed;
      } else if (current.status === 'failed') {
        color = THEME.colors.status.failed;
      } else if (current.status === 'running') {
        color = THEME.colors.status.running;
      }
    }

    return {
      flexGrow: 1,
      height: '1px',
      backgroundColor: color,
      margin: '0 8px',
      minWidth: '16px',
      alignSelf: 'center',
      transition: 'background-color 0.25s ease-in-out',
    };
  };

  return (
    <div
      className={`pipeline-visual-container ${className}`}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        width: '100%',
        backgroundColor: THEME.colors.surface1,
        padding: '24px 16px',
        border: THEME.borders.subtle,
        borderRadius: THEME.radius.card,
        overflowX: 'auto',
      }}
    >
      {gates.map((gate, index) => {
        const isActive = gate.id === activeGateId;
        const isClickable = !!onGateSelect;

        // Active node styling: slightly elevated surface, border, and left-accent line
        const nodeContainerStyle: React.CSSProperties = {
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          position: 'relative',
          cursor: isClickable ? 'pointer' : 'default',
        };

        // Render the 64-pixel-wide rectangle box containing the outcome pill
        const boxStyle: React.CSSProperties = {
          width: '64px',
          height: '36px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: isActive ? THEME.colors.surface3 : THEME.colors.surface2,
          border: isActive ? `1px solid ${THEME.colors.accent}` : THEME.borders.subtle,
          borderRadius: THEME.radius.card,
          position: 'relative',
          transition: 'all 0.25s ease-in-out',
          boxShadow: isActive ? `0 0 8px rgba(78, 201, 214, 0.15)` : 'none',
        };

        // Left edge accent stripe for the active gate
        const accentStripeStyle: React.CSSProperties = {
          position: 'absolute',
          left: 0,
          top: '4px',
          bottom: '4px',
          width: '3px',
          backgroundColor: THEME.colors.accent,
          borderRadius: '1px',
          display: isActive ? 'block' : 'none',
        };

        // Render label styling centered below the box
        const labelStyle: React.CSSProperties = {
          marginTop: '8px',
          fontFamily: THEME.fonts.sans,
          fontSize: '11px',
          fontWeight: isActive ? 600 : 500,
          color: isActive ? THEME.colors.textPrimary : THEME.colors.textSecondary,
          textAlign: 'center',
          whiteSpace: 'nowrap',
          maxWidth: '80px',
        };

        const idStyle: React.CSSProperties = {
          fontFamily: THEME.fonts.mono,
          fontSize: '9px',
          color: THEME.colors.textTertiary,
          marginBottom: '2px',
        };

        return (
          <React.Fragment key={gate.id}>
            {/* Gate Node */}
            <div
              className={`pipeline-gate-node ${isActive ? 'active' : ''}`}
              style={nodeContainerStyle}
              onClick={() => isClickable && handleGateClick(gate.id)}
            >
              <span style={idStyle}>{gate.id}</span>
              <div style={boxStyle}>
                <div style={accentStripeStyle} />
                {/* Scale the status pill small to fit clean inside the 64px box */}
                <StatusPill
                  status={gate.status}
                  label={gate.status.substring(0, 4)} // truncate to 4 chars for extreme density (e.g. "pass", "fail", "pend", "runn")
                  style={{
                    fontSize: '9px',
                    padding: '2px 4px',
                    lineHeight: 1,
                  }}
                />
              </div>
              <span style={labelStyle}>{gate.label}</span>
            </div>

            {/* Connecting line to the next gate (do not show after the last node) */}
            {index < gates.length - 1 && (
              <div
                className="pipeline-connector-line"
                style={getConnectorStyle(index)}
              />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
};
