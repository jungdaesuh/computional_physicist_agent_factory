/**
 * @file ComponentShowcase.tsx
 * @description Interactive visual verification and test harness for the factory UI component library.
 * Renders all component blocks under various states, allowing manual verification of interactive state,
 * scroll locks, search highlights, and dynamic visual styling.
 *
 * Use Cases:
 * - Local developer testing page for visual UI audits.
 * - Storybook-like documentation and state playground.
 */

import React, { useState, useEffect } from 'react';
import { THEME, logUIAction } from './theme';
import { StatusPill } from './StatusPill';
import { PipelineVisual, GateInfo } from './PipelineVisual';
import { LiveLogStream, LogEntry } from './LiveLogStream';
import { Sparkline } from './Sparkline';

/**
 * ComponentShowcase is a full-page developer sandbox.
 * Demonstrates all component combinations, states, animations, and inputs.
 */
export const ComponentShowcase: React.FC = () => {
  // State for active gate in the pipeline visualizer
  const [activeGate, setActiveGate] = useState<string>('G3');
  
  // State for pipeline gate statuses to show dynamic outcomes
  const [gateStates, setGateStates] = useState<GateInfo[]>([
    { id: 'G0', label: 'Domain', status: 'passed' },
    { id: 'G1', label: 'Falsifiability', status: 'passed' },
    { id: 'G1.5', label: 'Simulability', status: 'passed' },
    { id: 'G2', label: 'Worthiness', status: 'passed' },
    { id: 'G2.5', label: 'Tractability', status: 'running' },
    { id: 'G3', label: 'Surrogate', status: 'pending' },
    { id: 'G4', label: 'Validation', status: 'pending' },
    { id: 'G5', label: 'Interpretation', status: 'pending' },
    { id: 'G6', label: 'Human', status: 'pending' },
  ]);

  // State for streaming logs simulation
  const [simulatedLogs, setSimulatedLogs] = useState<LogEntry[]>([
    { id: '1', timestamp: '16:30:00', level: 'info', message: 'Initializing generator-verifier pipeline sandbox.' },
    { id: '2', timestamp: '16:30:02', level: 'info', message: 'Pulling simulator container image: registry.local/plasma-mhd:latest' },
    { id: '3', timestamp: '16:30:05', level: 'info', message: 'Container built. Base digest: sha256:4b971e...' },
    { id: '4', timestamp: '16:30:06', level: 'warn', message: 'Deprecated numpy API call detected in simulator wrapper (line 42).' },
    { id: '5', timestamp: '16:30:10', level: 'info', message: 'Tractability check running. Verifying grid boundaries.' },
    { id: '6', timestamp: '16:30:15', level: 'error', message: 'Fidelity escalation failed: grid residual exceeds convergence tolerance (1e-4).' },
    { id: '7', timestamp: '16:30:16', level: 'info', message: 'Triggering rollback sequence to coarse grid.' },
    { id: '8', timestamp: '16:30:18', level: 'info', message: 'Warm starting optimizer from historical strategy elites.' },
  ]);

  // Sparkline mock datasets
  const dollarBurnData = [12.4, 15.6, 22.1, 18.3, 30.5, 45.2, 38.0, 52.6, 44.8, 60.1, 75.3, 89.2, 70.4, 95.8, 110.2];
  const flatData = [42.0, 42.0, 42.0, 42.0, 42.0, 42.0, 42.0, 42.0, 42.0, 42.0];
  const agreementRateData = [0.45, 0.48, 0.52, 0.61, 0.73, 0.65, 0.58, 0.82, 0.91, 0.86, 0.72, 0.63, 0.51, 0.55, 0.68];

  // Simulating log appends every few seconds
  useEffect(() => {
    const messages = [
      { level: 'info' as const, msg: 'Evaluating optimization parameters: theta_1 = 0.523' },
      { level: 'info' as const, msg: 'MHD stability check: magnetic shear is within safety margin.' },
      { level: 'warn' as const, msg: 'OpenRouter API latency is high (1800ms). Retrying with backup endpoint.' },
      { level: 'info' as const, msg: 'Iterative residual norm decreased to 4.23e-6.' },
      { level: 'error' as const, msg: 'Physics boundary violation: Divergence of B-field non-zero! grad_B = 1.45e-2.' },
      { level: 'info' as const, msg: 'Resetting optimizer constraints and repopulating seed set.' }
    ];

    const interval = setInterval(() => {
      const nextLogIdx = Math.floor(Math.random() * messages.length);
      const chosen = messages[nextLogIdx];
      const now = new Date();
      const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;
      
      setSimulatedLogs((prev) => [
        ...prev,
        {
          id: `sim-${Date.now()}-${nextLogIdx}`,
          timestamp: timeStr,
          level: chosen.level,
          message: chosen.msg
        }
      ]);
    }, 4000);

    return () => clearInterval(interval);
  }, []);

  const handleGateSelect = (gateId: string) => {
    logUIAction('ComponentShowcase', 'handleGateSelect', { gateId });
    setActiveGate(gateId);
    
    // Cycle statuses to reflect realistic flow on selection changes
    setGateStates((prev) =>
      prev.map((g) => {
        if (g.id === gateId) {
          return { ...g, status: 'running' };
        } else if (g.id < gateId) {
          return { ...g, status: 'passed' };
        } else {
          return { ...g, status: 'pending' };
        }
      })
    );
  };

  const handleClear = () => {
    logUIAction('ComponentShowcase', 'handleClear', {});
    setSimulatedLogs([]);
  };

  return (
    <div
      style={{
        backgroundColor: THEME.colors.background,
        color: THEME.colors.textPrimary,
        fontFamily: THEME.fonts.sans,
        minHeight: '100vh',
        padding: '32px',
        display: 'flex',
        flexDirection: 'column',
        gap: '32px',
      }}
    >
      {/* Header */}
      <div>
        <h1 style={{ fontSize: '20px', fontWeight: 600, letterSpacing: '-0.02em', margin: '0 0 4px 0' }}>
          AI Co-Computational Physicist Component Showcase
        </h1>
        <p style={{ fontSize: '13px', color: THEME.colors.textSecondary, margin: 0 }}>
          Interactive playground for visual regression auditing and UX alignment.
        </p>
      </div>

      {/* Grid Row: Status Pills & Sparklines */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '24px' }}>
        {/* Status Pills Section */}
        <div
          style={{
            backgroundColor: THEME.colors.surface1,
            border: THEME.borders.subtle,
            borderRadius: THEME.radius.card,
            padding: '20px',
          }}
        >
          <h2 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '16px', borderBottom: THEME.borders.subtle, paddingBottom: '8px' }}>
            1. StatusPill Variants
          </h2>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            <StatusPill status="passed" />
            <StatusPill status="failed" />
            <StatusPill status="pending" />
            <StatusPill status="running" />
            <StatusPill status="dissent" />
            <StatusPill status="qualified" />
            <StatusPill status="parked" />
            <StatusPill status="passed" label="custom label" />
            <StatusPill status="failed" onClick={() => alert('Pill clicked')} />
          </div>
        </div>

        {/* Sparklines Section */}
        <div
          style={{
            backgroundColor: THEME.colors.surface1,
            border: THEME.borders.subtle,
            borderRadius: THEME.radius.card,
            padding: '20px',
          }}
        >
          <h2 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '16px', borderBottom: THEME.borders.subtle, paddingBottom: '8px' }}>
            2. Minimal Sparkline Charts (Interactive)
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: THEME.colors.textSecondary, marginBottom: '4px' }}>
                <span>Daily Dollar Burn ($)</span>
                <span>Max: $110.20</span>
              </div>
              <Sparkline data={dollarBurnData} height={36} />
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: THEME.colors.textSecondary, marginBottom: '4px' }}>
                <span>Council Agreement Rate (Sycophancy Risk threshold: 0.80)</span>
                <span style={{ color: THEME.colors.status.pending }}>Threshold Warning Enabled</span>
              </div>
              <Sparkline
                data={agreementRateData}
                height={36}
                threshold={0.80}
                strokeColor={THEME.colors.accent}
              />
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: THEME.colors.textSecondary, marginBottom: '4px' }}>
                <span>Flat telemetry response (Zero Variance)</span>
                <span>Value: 42.0</span>
              </div>
              <Sparkline data={flatData} height={30} strokeColor={THEME.colors.textTertiary} showArea={false} smooth={false} />
            </div>
          </div>
        </div>
      </div>

      {/* Row: Pipeline Visual */}
      <div
        style={{
          backgroundColor: THEME.colors.surface1,
          border: THEME.borders.subtle,
          borderRadius: THEME.radius.card,
          padding: '20px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 style={{ fontSize: '14px', fontWeight: 600, margin: 0 }}>
            3. 9-Gate Pipeline Visualizer
          </h2>
          <span style={{ fontSize: '11px', color: THEME.colors.textSecondary }}>
            Active Gate: <code style={{ fontFamily: THEME.fonts.mono, color: THEME.colors.accent }}>{activeGate}</code> (Click node to shift sequence)
          </span>
        </div>
        <PipelineVisual
          activeGateId={activeGate}
          gates={gateStates}
          onGateSelect={handleGateSelect}
        />
      </div>

      {/* Row: Live Log Stream */}
      <div
        style={{
          backgroundColor: THEME.colors.surface1,
          border: THEME.borders.subtle,
          borderRadius: THEME.radius.card,
          padding: '20px',
        }}
      >
        <h2 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '16px', borderBottom: THEME.borders.subtle, paddingBottom: '8px' }}>
          4. Live Monospace stdout Stream (Simulated Appends)
        </h2>
        <LiveLogStream
          logs={simulatedLogs}
          height="280px"
          onClearLogs={handleClear}
        />
      </div>
    </div>
  );
};
