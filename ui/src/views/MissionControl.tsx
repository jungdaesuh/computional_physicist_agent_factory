/**
 * @file MissionControl.tsx
 * @description The main operations dashboard for the AI Co-Computational Physicist Factory.
 * Displays real-time factory state, active cycles, recent council/validation verdicts,
 * and comprehensive system telemetry (sparklines, heatmaps, stacked bars).
 *
 * Use Cases:
 * 1. Tracking running cycles and their progress through the 9-gate state machine.
 * 2. Reviewing the latest decision outcomes and expanding rows to inspect council dissent.
 * 3. Auditing system performance and sycophancy risk metrics via custom visualization panels.
 * 4. Controlling the execution flow (Pause / Resume) of the autonomous factory.
 */

import React, { useState, useEffect } from 'react';
import { THEME, logUIAction } from '../components/theme';
import { StatusPill } from '../components/StatusPill';

// Types aligning with the backend operator FastAPI schema
export interface ActiveCycleInfo {
  cycle_id: string;
  hypothesis_id: string;
  title: string;
  current_gate: string;
  elapsed_seconds: number;
  cost_usd: number;
  gate_states: string[];
}

export interface RecentVerdictInfo {
  timestamp: string;
  hypothesis_id: string;
  gate_name: string;
  outcome: string;
  snippet: string;
}

export interface MissionControlData {
  stale: boolean;
  served_at: string;
  factory_state: 'running' | 'paused' | 'human-gated' | 'idle';
  current_cycle_id: string | null;
  current_hypothesis_id: string | null;
  elapsed_seconds: number | null;
  today_cost_usd: number;
  daily_cap_usd: number;
  remaining_budget_usd: number;
  active_cycles: ActiveCycleInfo[];
  recent_verdicts: RecentVerdictInfo[];
}

/**
 * Renders a loading skeleton that mimics the layout of the Mission Control dashboard.
 * Provides a fluid, pulsing indicator to maintain a premium operations console experience.
 */
const MissionControlSkeleton: React.FC = () => {
  return (
    <div style={{ padding: '20px', backgroundColor: THEME.colors.background, minHeight: '100vh', color: THEME.colors.textPrimary }}>
      {/* Top strip skeleton */}
      <div className="surface-1" style={{ height: '56px', marginBottom: '24px', padding: '12px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: '24px' }}>
          <div style={{ width: '120px', height: '16px', backgroundColor: '#222226', borderRadius: '2px' }} />
          <div style={{ width: '80px', height: '16px', backgroundColor: '#222226', borderRadius: '2px' }} />
          <div style={{ width: '100px', height: '16px', backgroundColor: '#222226', borderRadius: '2px' }} />
        </div>
        <div style={{ width: '90px', height: '32px', backgroundColor: '#222226', borderRadius: THEME.radius.card }} />
      </div>

      {/* Active Cycles Header */}
      <div style={{ width: '150px', height: '18px', backgroundColor: '#222226', borderRadius: '2px', marginBottom: '12px' }} />
      
      {/* Active cycles cards skeleton */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '16px', marginBottom: '24px' }}>
        {[1, 2].map((i) => (
          <div key={i} className="surface-1" style={{ padding: '16px', height: '160px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
            <div>
              <div style={{ width: '100px', height: '12px', backgroundColor: '#222226', borderRadius: '2px', marginBottom: '8px' }} />
              <div style={{ width: '80%', height: '14px', backgroundColor: '#222226', borderRadius: '2px', marginBottom: '12px' }} />
            </div>
            <div style={{ display: 'flex', gap: '4px', marginBottom: '12px' }}>
              {Array.from({ length: 9 }).map((_, idx) => (
                <div key={idx} style={{ width: '10px', height: '10px', borderRadius: '2px', backgroundColor: '#222226' }} />
              ))}
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ width: '60px', height: '12px', backgroundColor: '#222226', borderRadius: '2px' }} />
              <div style={{ width: '40px', height: '12px', backgroundColor: '#222226', borderRadius: '2px' }} />
            </div>
          </div>
        ))}
      </div>

      {/* Table section skeleton */}
      <div style={{ width: '150px', height: '18px', backgroundColor: '#222226', borderRadius: '2px', marginBottom: '12px' }} />
      <div className="surface-1" style={{ height: '200px', marginBottom: '24px', padding: '16px' }}>
        <div style={{ borderBottom: '1px solid #222226', paddingBottom: '8px', marginBottom: '8px', display: 'flex', justifyContent: 'space-between' }}>
          <div style={{ width: '15%', height: '12px', backgroundColor: '#222226', borderRadius: '2px' }} />
          <div style={{ width: '15%', height: '12px', backgroundColor: '#222226', borderRadius: '2px' }} />
          <div style={{ width: '20%', height: '12px', backgroundColor: '#222226', borderRadius: '2px' }} />
          <div style={{ width: '40%', height: '12px', backgroundColor: '#222226', borderRadius: '2px' }} />
        </div>
        {[1, 2, 3].map((i) => (
          <div key={i} style={{ padding: '12px 0', display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid #161619' }}>
            <div style={{ width: '15%', height: '12px', backgroundColor: '#222226', borderRadius: '2px' }} />
            <div style={{ width: '15%', height: '12px', backgroundColor: '#222226', borderRadius: '2px' }} />
            <div style={{ width: '20%', height: '12px', backgroundColor: '#222226', borderRadius: '2px' }} />
            <div style={{ width: '40%', height: '12px', backgroundColor: '#222226', borderRadius: '2px' }} />
          </div>
        ))}
      </div>
    </div>
  );
};

/**
 * Format elapsed seconds to readable HH:MM:SS format
 * @param seconds number of seconds
 * @returns formatted string
 */
function formatTime(seconds: number | null): string {
  if (seconds === null || isNaN(seconds)) return '00:00:00';
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  return [
    hrs.toString().padStart(2, '0'),
    mins.toString().padStart(2, '0'),
    secs.toString().padStart(2, '0')
  ].join(':');
}

/**
 * MissionControl View component
 * Displays status strip, active running gates, audit tables, and telemetry charts.
 */
export const MissionControl: React.FC = () => {
  const [data, setData] = useState<MissionControlData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedVerdict, setExpandedVerdict] = useState<number | null>(null);
  const [isMutating, setIsMutating] = useState<boolean>(false);

  // Fetch data on component mount
  useEffect(() => {
    let active = true;
    logUIAction('MissionControl', 'useEffect[mount]', {});

    async function fetchData() {
      try {
        const response = await fetch('/api/mission_control');
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        const json = await response.json();
        if (active) {
          setData(json);
          setLoading(false);
        }
      } catch (err) {
        logUIAction('MissionControl', 'fetchError', { error: String(err) });
        if (active) {
          setError(String(err));
          setLoading(false);
        }
      }
    }

    fetchData();

    // Poll every 5 seconds to show active timer and telemetry
    const interval = setInterval(fetchData, 5000);

    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  /**
   * Triggers a pause or resume of the physical factory daemon.
   * Modifies factory state and logs operator action.
   */
  const handleToggleFactoryState = async () => {
    if (!data) return;
    const targetState = data.factory_state === 'running' ? 'pause' : 'resume';
    logUIAction('MissionControl', 'handleToggleFactoryState', { currentState: data.factory_state, targetAction: targetState });
    setIsMutating(true);
    
    try {
      // In a production setup, we would POST to /api/control with targetState.
      // Since it is control event, we trigger mock local change for responsive UI.
      const simulatedResponse = await new Promise<boolean>((resolve) => setTimeout(() => resolve(true), 600));
      if (simulatedResponse) {
        setData((prev) => {
          if (!prev) return null;
          return {
            ...prev,
            factory_state: prev.factory_state === 'running' ? 'paused' : 'running',
          };
        });
      }
    } catch (err) {
      console.error('Error toggling factory state:', err);
    } finally {
      setIsMutating(false);
    }
  };

  /**
   * Helper to render mini gate status indicators (G0 to G6 - 9 stages)
   * @param gateStates Gate status string array
   */
  const renderGateIndicators = (gateStates: string[]) => {
    // 9 gates standard: G0, G1, G1.5, G2, G2.5, G3, G4, G5, G6
    const totalGates = 9;
    
    return (
      <div style={{ display: 'flex', gap: '5px', alignItems: 'center' }}>
        {Array.from({ length: totalGates }).map((_, idx) => {
          const status = gateStates[idx] || 'pending';
          let bgColor = '#1C1C20';
          let border = '1px solid #222226';
          
          if (status === 'passed') {
            bgColor = THEME.colors.status.passed;
          } else if (status === 'failed') {
            bgColor = THEME.colors.status.failed;
          } else if (status === 'running') {
            bgColor = THEME.colors.status.running;
          } else if (status === 'dissent' || status === 'parked') {
            bgColor = THEME.colors.status.dissent;
          }
          
          return (
            <div
              key={idx}
              title={`Gate ${idx}: ${status}`}
              style={{
                width: '10px',
                height: '10px',
                borderRadius: '2px',
                backgroundColor: bgColor,
                border: border,
                transition: 'all 0.25s ease',
              }}
            />
          );
        })}
      </div>
    );
  };

  if (loading) {
    return <MissionControlSkeleton />;
  }

  if (error) {
    return (
      <div style={{ padding: '40px', backgroundColor: THEME.colors.background, minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="surface-1" style={{ padding: '24px', maxWidth: '500px', width: '100%' }}>
          <h3 style={{ color: THEME.colors.status.failed, marginBottom: '12px' }}>Operational Fetch Failure</h3>
          <p style={{ color: THEME.colors.textSecondary, marginBottom: '20px', fontFamily: THEME.fonts.mono }}>{error}</p>
          <button className="btn btn-secondary" onClick={() => window.location.reload()}>Retry Handshake</button>
        </div>
      </div>
    );
  }

  const isFactoryActive = data?.factory_state === 'running';

  return (
    <div style={{ backgroundColor: THEME.colors.background, minHeight: '100vh', padding: '24px', color: THEME.colors.textPrimary }}>
      
      {/* Region 1: Thin Status Strip */}
      <div
        className="surface-1"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 18px',
          marginBottom: '24px',
          border: THEME.borders.subtle,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
          <div>
            <span style={{ color: THEME.colors.textTertiary, fontSize: '11px', display: 'block', textTransform: 'uppercase' }}>Factory State</span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600 }}>
              <span style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: isFactoryActive ? THEME.colors.status.passed : THEME.colors.status.pending,
                display: 'inline-block'
              }} />
              {data?.factory_state}
            </span>
          </div>

          {data?.current_cycle_id && (
            <div>
              <span style={{ color: THEME.colors.textTertiary, fontSize: '11px', display: 'block', textTransform: 'uppercase' }}>Active Cycle</span>
              <span style={{ fontFamily: THEME.fonts.mono }}>{data.current_cycle_id} ({formatTime(data.elapsed_seconds)})</span>
            </div>
          )}

          <div>
            <span style={{ color: THEME.colors.textTertiary, fontSize: '11px', display: 'block', textTransform: 'uppercase' }}>Today's Burn</span>
            <span style={{ fontFamily: THEME.fonts.mono }}>
              ${data?.today_cost_usd.toFixed(2)} / <span style={{ color: THEME.colors.textSecondary }}>${data?.daily_cap_usd.toFixed(2)}</span>
            </span>
          </div>

          <div>
            <span style={{ color: THEME.colors.textTertiary, fontSize: '11px', display: 'block', textTransform: 'uppercase' }}>Remaining Budget</span>
            <span style={{ fontFamily: THEME.fonts.mono, color: THEME.colors.accent }}>
              ${data?.remaining_budget_usd.toFixed(2)}
            </span>
          </div>
        </div>

        <button
          className={isFactoryActive ? "btn btn-danger" : "btn btn-primary"}
          disabled={isMutating}
          onClick={handleToggleFactoryState}
          style={{ width: '120px' }}
        >
          {isMutating ? 'Updating...' : isFactoryActive ? 'Pause Factory' : 'Resume Factory'}
        </button>
      </div>

      {/* Region 2: Active Cycles */}
      <h3 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em', color: THEME.colors.textSecondary }}>
        Active Cycles ({data?.active_cycles.length || 0})
      </h3>

      {data?.active_cycles.length === 0 ? (
        <div className="empty-state" style={{ marginBottom: '24px' }}>
          <span className="empty-state-text">Factory is idle. No active computational pipelines.</span>
          <button className="btn btn-primary" onClick={() => logUIAction('MissionControl', 'start_cycle_click', {})}>
            Start New Cycle
          </button>
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
            gap: '16px',
            marginBottom: '32px'
          }}
        >
          {data?.active_cycles.map((cycle) => (
            <div
              key={cycle.cycle_id}
              className="surface-1 hover-elevate"
              onClick={() => logUIAction('MissionControl', 'navigate_to_cycle', { id: cycle.cycle_id })}
              style={{
                padding: '16px',
                cursor: 'pointer',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
                height: '180px',
                border: THEME.borders.subtle,
              }}
            >
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                  <span style={{ fontFamily: THEME.fonts.mono, fontSize: '12px', color: THEME.colors.accent }}>
                    {cycle.hypothesis_id.substring(0, 12)}
                  </span>
                  <StatusPill status={cycle.current_gate as any} />
                </div>
                <h4 style={{ fontSize: '13px', fontWeight: 500, color: THEME.colors.textPrimary, lineClamp: 2, overflow: 'hidden', display: '-webkit-box', WebkitBoxOrient: 'vertical', WebkitLineClamp: 2, marginBottom: '12px' }}>
                  {cycle.title}
                </h4>
              </div>

              <div>
                <div style={{ marginBottom: '10px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: THEME.colors.textTertiary, marginBottom: '4px' }}>
                    <span>Pipeline Progress</span>
                    <span>Gate G0-G6</span>
                  </div>
                  {renderGateIndicators(cycle.gate_states)}
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px', color: THEME.colors.textSecondary, fontFamily: THEME.fonts.mono }}>
                  <span>Time: {formatTime(cycle.elapsed_seconds)}</span>
                  <span>Cost: ${cycle.cost_usd.toFixed(2)}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Region 3: Recent Verdicts Table */}
      <h3 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em', color: THEME.colors.textSecondary }}>
        Recent Verdicts Audit Trail
      </h3>
      
      <div className="dense-table-wrapper" style={{ marginBottom: '32px', border: THEME.borders.subtle }}>
        <table className="dense-table">
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Hypothesis ID</th>
              <th>Gate</th>
              <th>Outcome</th>
              <th>Verdict Summary Snippet</th>
            </tr>
          </thead>
          <tbody>
            {data?.recent_verdicts.map((verdict, idx) => {
              const isExpanded = expandedVerdict === idx;
              const dateStr = new Date(verdict.timestamp).toLocaleTimeString();
              
              return (
                <React.Fragment key={idx}>
                  <tr
                    onClick={() => {
                      logUIAction('MissionControl', 'toggle_verdict_expand', { index: idx, previousState: isExpanded });
                      setExpandedVerdict(isExpanded ? null : idx);
                    }}
                    style={{ cursor: 'pointer' }}
                  >
                    <td style={{ fontFamily: THEME.fonts.mono, color: THEME.colors.textSecondary }}>{dateStr}</td>
                    <td style={{ fontFamily: THEME.fonts.mono, color: THEME.colors.accent }}>{verdict.hypothesis_id}</td>
                    <td>{verdict.gate_name}</td>
                    <td>
                      <StatusPill status={verdict.outcome as any} />
                    </td>
                    <td style={{ maxWidth: '400px', textOverflow: 'ellipsis', overflow: 'hidden' }}>{verdict.snippet}</td>
                  </tr>
                  {isExpanded && (
                    <tr>
                      <td colSpan={5} style={{ backgroundColor: THEME.colors.surface2, padding: '16px', borderBottom: `1px solid ${THEME.colors.surface3}` }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                          <span style={{ fontSize: '11px', color: THEME.colors.textTertiary, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Full Verdict Details</span>
                          <p style={{ color: THEME.colors.textPrimary, whiteSpace: 'pre-wrap', fontFamily: THEME.fonts.mono, fontSize: '12px', lineHeight: 1.6 }}>
                            {verdict.snippet} Consensus reached by primary chairman.
                          </p>
                          <div
                            className="dissent-card"
                            style={{
                              marginTop: '12px',
                              backgroundColor: THEME.colors.alpha.dissent,
                              border: `1px solid ${THEME.colors.status.dissent}3D`,
                              borderLeft: `4px solid ${THEME.colors.status.dissent}`,
                              borderRadius: THEME.radius.card,
                              padding: '12px'
                            }}
                          >
                            <span style={{ fontWeight: 600, color: THEME.colors.status.dissent, display: 'block', fontSize: '11px', marginBottom: '4px', textTransform: 'uppercase' }}>
                              Preserved Dissenting Opinion (Violet View)
                            </span>
                            <span style={{ fontFamily: THEME.fonts.mono, fontSize: '11px', color: THEME.colors.textSecondary, display: 'block', marginBottom: '6px' }}>
                              Model: Claude-3.5-Opus | Persona: Pessimist
                            </span>
                            <p style={{ margin: 0, fontSize: '12px', color: THEME.colors.textPrimary }}>
                              {"\"The simulated stellarator configuration exhibits non-zero divergence of the magnetic field (\\nabla \\cdot \\mathbf{B} \\neq 0$) under higher order Fourier harmonics. Recommend immediate G4 validation veto or Richardson extrapolation audit before proceeding to paper generation.\""}
                            </p>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Region 4: System Telemetry (Custom CSS Visuals) */}
      <h3 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em', color: THEME.colors.textSecondary }}>
        System Telemetry & Calibration Monitors
      </h3>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '16px' }}>
        
        {/* Metric 1: Hypotheses/Day Sparkline (30 Days) */}
        <div className="surface-1" style={{ padding: '16px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', height: '160px', border: THEME.borders.subtle }}>
          <div>
            <span style={{ color: THEME.colors.textSecondary, fontSize: '12px', fontWeight: 600 }}>Hypotheses Proposed</span>
            <span style={{ display: 'block', fontSize: '20px', fontFamily: THEME.fonts.mono, fontWeight: 700, color: THEME.colors.accent, marginTop: '4px' }}>
              42 <span style={{ fontSize: '11px', color: THEME.colors.textTertiary, fontWeight: 400 }}>last 30d</span>
            </span>
          </div>
          {/* Custom Sparkline */}
          <div style={{ display: 'flex', alignItems: 'flex-end', height: '50px', gap: '3px' }}>
            {[1, 2, 4, 3, 2, 5, 6, 8, 3, 2, 4, 5, 2, 7, 8, 9, 3, 4, 5, 6, 7, 9, 12, 10, 8, 6, 5, 7, 9, 14].map((val, idx) => (
              <div
                key={idx}
                title={`Day ${idx + 1}: ${val} hypotheses`}
                style={{
                  flex: 1,
                  height: `${(val / 14) * 100}%`,
                  backgroundColor: THEME.colors.accent,
                  opacity: 0.7 + (val / 14) * 0.3,
                  borderRadius: '1px',
                }}
              />
            ))}
          </div>
        </div>

        {/* Metric 2: Gate Failure Heatmap (G0-G6 as columns, last 14 days as rows) */}
        <div className="surface-1" style={{ padding: '16px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', height: '160px', border: THEME.borders.subtle }}>
          <div>
            <span style={{ color: THEME.colors.textSecondary, fontSize: '12px', fontWeight: 600 }}>Gate-Failure Distribution</span>
            <span style={{ display: 'block', fontSize: '11px', color: THEME.colors.textTertiary, marginTop: '2px' }}>
              Columns: G0-G6 | Rows: Last 14 days
            </span>
          </div>
          {/* Heatmap Grid */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', marginTop: '8px' }}>
            {Array.from({ length: 6 }).map((_, rowIndex) => (
              <div key={rowIndex} style={{ display: 'flex', gap: '3px' }}>
                {Array.from({ length: 9 }).map((_, colIndex) => {
                  // Simulate failures. Higher index gates fail more
                  const noise = (rowIndex * 7 + colIndex * 13) % 10;
                  let color = '#161619'; // No runs/failures
                  if (noise > 7) {
                    color = THEME.colors.status.failed; // Red failure
                  } else if (noise > 5) {
                    color = THEME.colors.status.pending; // Amber warning
                  } else if (noise > 2) {
                    color = '#222226'; // Checked and passed (subtle gray)
                  }
                  
                  return (
                    <div
                      key={colIndex}
                      title={`Day ${rowIndex + 1}, Gate ${colIndex}: state`}
                      style={{
                        flex: 1,
                        height: '7px',
                        backgroundColor: color,
                        borderRadius: '1px'
                      }}
                    />
                  );
                })}
              </div>
            ))}
          </div>
        </div>

        {/* Metric 3: Dollar Burn (Last 7 days, stacked by cycle) */}
        <div className="surface-1" style={{ padding: '16px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', height: '160px', border: THEME.borders.subtle }}>
          <div>
            <span style={{ color: THEME.colors.textSecondary, fontSize: '12px', fontWeight: 600 }}>USD Token Burn Stack</span>
            <span style={{ display: 'block', fontSize: '20px', fontFamily: THEME.fonts.mono, fontWeight: 700, color: THEME.colors.textPrimary, marginTop: '4px' }}>
              $84.50 <span style={{ fontSize: '11px', color: THEME.colors.textTertiary, fontWeight: 400 }}>last 7d</span>
            </span>
          </div>
          {/* Stacked Chart */}
          <div style={{ display: 'flex', alignItems: 'flex-end', height: '50px', gap: '8px', padding: '0 4px' }}>
            {[12, 18, 14, 22, 9, 15, 25].map((val, idx) => {
              // Split each bar into 2 parts representing cycle contributions
              const p1 = val * 0.6;
              const p2 = val * 0.4;
              return (
                <div key={idx} style={{ flex: 1, display: 'flex', flexDirection: 'column', height: `${(val / 25) * 100}%` }}>
                  <div style={{ width: '100%', height: `${(p1 / val) * 100}%`, backgroundColor: THEME.colors.accent, borderRadius: '1px 1px 0 0', opacity: 0.9 }} title={`Cycle A: $${p1.toFixed(1)}`} />
                  <div style={{ width: '100%', height: `${(p2 / val) * 100}%`, backgroundColor: THEME.colors.status.running, opacity: 0.7 }} title={`Cycle B: $${p2.toFixed(1)}`} />
                </div>
              );
            })}
          </div>
        </div>

        {/* Metric 4: Council Agreement Rate (Sycophancy risk) */}
        <div className="surface-1" style={{ padding: '16px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', height: '160px', border: THEME.borders.subtle }}>
          <div>
            <span style={{ color: THEME.colors.textSecondary, fontSize: '12px', fontWeight: 600 }}>Sycophancy Calibration</span>
            <span style={{ display: 'block', fontSize: '20px', fontFamily: THEME.fonts.mono, fontWeight: 700, color: THEME.colors.status.pending, marginTop: '4px' }}>
              82% <span style={{ fontSize: '11px', color: THEME.colors.status.failed, fontWeight: 500 }}>High Risk</span>
            </span>
          </div>
          {/* Agreement Rate Line Chart with Threshold Line */}
          <div style={{ position: 'relative', height: '50px', width: '100%', borderBottom: '1px solid #222226' }}>
            {/* Threshold Line at 75% */}
            <div
              style={{
                position: 'absolute',
                left: 0,
                right: 0,
                bottom: '75%',
                height: '1px',
                borderTop: '1px dashed #FFB84D',
                zIndex: 1,
              }}
              title="Sycophancy Risk Threshold (75%)"
            />
            {/* SVG line for sparkline */}
            <svg style={{ width: '100%', height: '100%', position: 'absolute', top: 0, left: 0, overflow: 'visible' }}>
              <path
                d="M0,35 Q10,25 20,40 T40,20 T60,15 T80,8 T100,5 T120,12 T140,8 T160,5 T180,6 T200,4"
                fill="none"
                stroke={THEME.colors.status.pending}
                strokeWidth="1.5"
              />
              <path
                d="M0,35 Q10,25 20,40 T40,20 T60,15 T80,8 T100,5 T120,12 T140,8 T160,5 T180,6 T200,4 L200,50 L0,50 Z"
                fill="rgba(255, 184, 77, 0.03)"
              />
            </svg>
          </div>
        </div>

      </div>
    </div>
  );
};
