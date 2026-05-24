/**
 * @file DeliberationView.tsx
 * @description Detailed audit viewer for the Multi-LLM Deliberation Council.
 * Visualizes the consensus-building pipeline: Stage 1 (First Opinions),
 * Stage 2 (Anonymized Cross-Review Matrix), and Stage 3 (Chairman Synthesis with Preserved Dissent).
 *
 * Use Cases:
 * 1. Auditing how AI models reached Worthiness (C1), Design (C2), or Peer Review (C4) decisions.
 * 2. Uncovering model sycophancy by analyzing dissenting cards rendered in violet.
 * 3. Inspecting the anonymized review matrix and toggling identity mapping (Voice A -> Model ID).
 * 4. Re-evaluating claims by reading specific critiques and scores assigned by each persona.
 */

import React, { useState, useEffect } from 'react';
import { THEME, logUIAction } from '../components/theme';
import { StatusPill } from '../components/StatusPill';

// Types representing the backend schemas
export interface DissentEntry {
  model_id: string;
  persona: 'visionary' | 'pessimist' | 'pragmatist';
  view: string;
  rationale: string;
}

export interface CouncilVerdict {
  artifact_type: string;
  created_at: string;
  provenance_hash: string;
  parent_hashes: string[];
  council_id: string;
  question: string;
  model_lineup: string[];
  persona_assignment: Record<string, 'visionary' | 'pessimist' | 'pragmatist'>;
  chairman_model: string;
  majority_view: string;
  preserved_dissents: DissentEntry[];
  chairman_decision: 'approve' | 'reject' | 'qualified' | 'no_consensus';
  total_cost_usd: number;
  wall_clock_seconds: number;
  session_id: string;
}

export interface DeliberationResponse {
  stale: boolean;
  served_at: string;
  verdict: CouncilVerdict;
}

export interface DeliberationViewProps {
  /** The session ID representing a single Council deliberation run */
  sessionId?: string;
  /** Callback to trigger comparison mode with prior verdicts */
  onComparePrior?: (question: string) => void;
}

// Interface for simulated Stage 1 and Stage 2 details
interface SimulatedOpinion {
  modelId: string;
  persona: string;
  score: number;
  opinionText: string;
}

interface SimulatedCritique {
  reviewer: string;  // e.g. "Voice A"
  reviewee: string;  // e.g. "Voice B"
  critiqueText: string;
  scoreAssigned: number;
}

/**
 * Loading skeleton component for DeliberationView.
 * Uses clean borders and dark elevation colors to match the Vercel/Linear dark aesthetics.
 */
const DeliberationSkeleton: React.FC = () => {
  return (
    <div style={{ padding: '24px', backgroundColor: THEME.colors.background, minHeight: '100vh', color: THEME.colors.textPrimary }}>
      {/* Header skeleton */}
      <div className="surface-1" style={{ padding: '20px', marginBottom: '24px', height: '120px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
        <div style={{ width: '200px', height: '20px', backgroundColor: '#222226', borderRadius: '2px' }} />
        <div style={{ width: '80%', height: '14px', backgroundColor: '#222226', borderRadius: '2px' }} />
        <div style={{ display: 'flex', gap: '8px' }}>
          <div style={{ width: '100px', height: '16px', backgroundColor: '#222226', borderRadius: '2px' }} />
          <div style={{ width: '100px', height: '16px', backgroundColor: '#222226', borderRadius: '2px' }} />
        </div>
      </div>

      {/* Stage 1 skeleton */}
      <div style={{ width: '150px', height: '16px', backgroundColor: '#222226', borderRadius: '2px', marginBottom: '12px' }} />
      <div style={{ display: 'flex', gap: '16px', overflowX: 'auto', marginBottom: '24px', paddingBottom: '8px' }}>
        {[1, 2, 3].map((i) => (
          <div key={i} className="surface-1" style={{ minWidth: '320px', width: '320px', height: '180px', padding: '16px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
            <div style={{ width: '120px', height: '14px', backgroundColor: '#222226', borderRadius: '2px' }} />
            <div style={{ width: '100%', height: '80px', backgroundColor: '#222226', borderRadius: '2px', margin: '12px 0' }} />
            <div style={{ width: '50px', height: '12px', backgroundColor: '#222226', borderRadius: '2px' }} />
          </div>
        ))}
      </div>
    </div>
  );
};


/**
 * DeliberationView displays the multi-model consensus workflow in three stages:
 * opinions drafting, anonymous cross-critique matrix, and chairman final synthesis.
 */
const mapDecisionToStatus = (decision: 'approve' | 'reject' | 'qualified' | 'no_consensus'): 'passed' | 'failed' | 'qualified' | 'dissent' | 'pending' => {
  switch (decision) {
    case 'approve':
      return 'passed';
    case 'reject':
      return 'failed';
    case 'qualified':
      return 'qualified';
    case 'no_consensus':
      return 'dissent';
    default:
      return 'pending';
  }
};

export const DeliberationView: React.FC<DeliberationViewProps> = ({
  sessionId = 'mock-session-123',
  onComparePrior,
}) => {
  const [verdict, setVerdict] = useState<CouncilVerdict | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  
  // Interactive triggers
  const [revealIdentities, setRevealIdentities] = useState<boolean>(false);
  const [expandOpinions, setExpandOpinions] = useState<boolean>(false);
  const [expandedCritique, setExpandedCritique] = useState<{ r: string; e: string } | null>(null);

  // Fetch the verdict details from API on mount or session change
  useEffect(() => {
    let active = true;
    setLoading(true);
    logUIAction('DeliberationView', 'useEffect[sessionId]', { sessionId });

    async function fetchVerdict() {
      try {
        const response = await fetch(`/api/verdicts/${sessionId}`);
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data: DeliberationResponse = await response.json();
        if (active) {
          setVerdict(data.verdict);
          setLoading(false);
        }
      } catch (err) {
        logUIAction('DeliberationView', 'fetchError', { error: String(err) });
        if (active) {
          setError(String(err));
          setLoading(false);
        }
      }
    }

    fetchVerdict();
    return () => {
      active = false;
    };
  }, [sessionId]);

  /**
   * Helper to map index to Voice names (Voice A, Voice B, Voice C...)
   * @param index Model index
   */
  const getVoiceName = (index: number): string => {
    return `Voice ${String.fromCharCode(65 + index)}`;
  };

  /**
   * Generate simulated opinions for Stage 1.
   * Based on the actual models in the lineup to make the mockup fully realistic.
   */
  const getSimulatedOpinions = (lineup: string[], personaMap: Record<string, string>): SimulatedOpinion[] => {
    return lineup.map((model) => {
      const persona = personaMap[model] || 'pragmatist';
      let opinionText = '';
      let score = 8;
      
      if (persona === 'visionary') {
        score = 9.5;
        opinionText = "This candidate represents an incredibly novel stellarator design path. Integrating high-fidelity DESC solvers with differentiable boundary search allows us to skip typical initial layout filters. Recommend immediate approval.";
      } else if (persona === 'pessimist') {
        score = 5.0;
        opinionText = "Fails to address basic simulability. Divergence of the magnetic field ($\\nabla \\cdot \\mathbf{B} = 0$) constraint is aggregated using static penalty weights, which will lead to numerical instability on coarser grids. We must enforce adaptive ALM multiplier schedules.";
      } else {
        score = 7.5;
        opinionText = "The convergence rate looks plausible under standard conditions. While the physical assumptions are solid, we must pre-screen with kNN surrogate probes at tier-1 to conserve budget before firing full oracle runs.";
      }

      return { modelId: model, persona, score, opinionText };
    });
  };

  /**
   * Generate simulated critiques for Stage 2 Anonymized Cross-Review.
   */
  const getSimulatedCritiques = (lineup: string[]): SimulatedCritique[] => {
    const critiques: SimulatedCritique[] = [];
    lineup.forEach((_reviewerModel, rIdx) => {
      lineup.forEach((_revieweeModel, eIdx) => {
        if (rIdx === eIdx) return; // cannot review oneself

        const reviewerVoice = getVoiceName(rIdx);
        const revieweeVoice = getVoiceName(eIdx);

        let critiqueText = '';
        let scoreAssigned = 8;

        if (rIdx === 0) { // Voice A is optimistic
          scoreAssigned = 9;
          critiqueText = `Highly aligned with the analytical formulation in ${revieweeVoice}. Strong bounds on optimization constraints.`;
        } else if (rIdx === 1) { // Voice B is pessimist
          scoreAssigned = 4;
          critiqueText = `The numerical convergence claimed in ${revieweeVoice} fails to specify spacing constraints. Invariant violation.`;
        } else { // Voice C is pragmatist
          scoreAssigned = 7;
          critiqueText = `Decent physical basis. A bit over-generalized; need to test specific parameter grids.`;
        }

        critiques.push({
          reviewer: reviewerVoice,
          reviewee: revieweeVoice,
          critiqueText,
          scoreAssigned,
        });
      });
    });
    return critiques;
  };

  if (loading) {
    return <DeliberationSkeleton />;
  }

  if (error || !verdict) {
    return (
      <div style={{ padding: '40px', backgroundColor: THEME.colors.background, minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="surface-1" style={{ padding: '24px', maxWidth: '500px', width: '100%' }}>
          <h3 style={{ color: THEME.colors.status.failed, marginBottom: '12px' }}>Verdict Loading Error</h3>
          <p style={{ color: THEME.colors.textSecondary, marginBottom: '20px', fontFamily: THEME.fonts.mono }}>{error || 'No verdict data returned'}</p>
          <button className="btn btn-secondary" onClick={() => window.location.reload()}>Retry handshake</button>
        </div>
      </div>
    );
  }

  // Generate simulated workflow data derived from actual lineup
  const opinions = getSimulatedOpinions(verdict.model_lineup, verdict.persona_assignment);
  const critiques = getSimulatedCritiques(verdict.model_lineup);

  return (
    <div style={{ backgroundColor: THEME.colors.background, minHeight: '100vh', padding: '24px', color: THEME.colors.textPrimary }}>
      
      {/* Header Panel */}
      <div
        className="surface-1"
        style={{
          padding: '20px',
          marginBottom: '24px',
          border: THEME.borders.subtle,
          display: 'flex',
          flexDirection: 'column',
          gap: '12px'
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
              <span style={{ fontSize: '12px', fontWeight: 600, color: THEME.colors.accent, fontFamily: THEME.fonts.mono, textTransform: 'uppercase' }}>
                Deliberation Session: {verdict.council_id}
              </span>
              <span style={{ color: THEME.colors.textTertiary }}>•</span>
              <span style={{ fontFamily: THEME.fonts.mono, fontSize: '11px', color: THEME.colors.textSecondary }}>{verdict.session_id}</span>
            </div>
            <h2 style={{ fontSize: '18px', fontWeight: 600, color: THEME.colors.textPrimary }}>
              Council Deliberation Audit Report
            </h2>
          </div>
          
          <div style={{ display: 'flex', gap: '8px' }}>
            {onComparePrior && (
              <button
                className="btn btn-secondary text-xs"
                onClick={() => {
                  logUIAction('DeliberationView', 'compare_prior', { question: verdict.question });
                  onComparePrior(verdict.question);
                }}
              >
                Compare with Prior Verdicts
              </button>
            )}
            <StatusPill status={mapDecisionToStatus(verdict.chairman_decision)} label={verdict.chairman_decision === 'no_consensus' ? 'No Consensus' : verdict.chairman_decision} />
          </div>
        </div>

        {/* Question Quote */}
        <blockquote
          style={{
            margin: '8px 0',
            padding: '10px 14px',
            backgroundColor: THEME.colors.surface2,
            borderLeft: `2px solid ${THEME.colors.accent}`,
            fontFamily: THEME.fonts.mono,
            fontSize: '12px',
            color: THEME.colors.textSecondary,
          }}
        >
          Question Put to Council: "{verdict.question}"
        </blockquote>

        {/* Model Lineup chips */}
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontSize: '11px', color: THEME.colors.textTertiary, textTransform: 'uppercase' }}>Lineup:</span>
          {verdict.model_lineup.map((model) => {
            const isChairman = model === verdict.chairman_model;
            const persona = verdict.persona_assignment[model] || 'pragmatist';
            
            return (
              <div
                key={model}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  backgroundColor: THEME.colors.surface3,
                  border: THEME.borders.subtle,
                  borderRadius: THEME.radius.card,
                  padding: '3px 8px',
                  fontSize: '11px',
                }}
              >
                {isChairman && (
                  <span title="Chairman Model" style={{ color: THEME.colors.status.pending, display: 'inline-flex', alignItems: 'center' }}>
                    👑
                  </span>
                )}
                <span style={{ fontFamily: THEME.fonts.mono, color: THEME.colors.textPrimary }}>{model}</span>
                <span style={{ color: THEME.colors.textTertiary }}>·</span>
                <span style={{ color: THEME.colors.textSecondary, textTransform: 'capitalize' }}>{persona}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* STAGE 1: First Opinions */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <h3 style={{ fontSize: '13px', textTransform: 'uppercase', letterSpacing: '0.05em', color: THEME.colors.textSecondary, display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontFamily: THEME.fonts.mono, color: THEME.colors.accent }}>01</span>
          Stage 1: First Opinions
        </h3>
        <button
          className="btn btn-secondary"
          style={{ fontSize: '11px', padding: '3px 8px' }}
          onClick={() => {
            logUIAction('DeliberationView', 'toggle_expand_opinions', { nextState: !expandOpinions });
            setExpandOpinions(!expandOpinions);
          }}
        >
          {expandOpinions ? 'Collapse All' : 'Expand All'}
        </button>
      </div>

      <div
        className="custom-scrollbar"
        style={{
          display: 'flex',
          gap: '16px',
          overflowX: 'auto',
          paddingBottom: '12px',
          marginBottom: '32px',
        }}
      >
        {opinions.map((op) => (
          <div
            key={op.modelId}
            className="surface-1"
            style={{
              minWidth: '320px',
              width: '320px',
              padding: '16px',
              border: THEME.borders.subtle,
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              maxHeight: expandOpinions ? 'none' : '220px',
              transition: 'max-height 0.25s ease-in-out',
            }}
          >
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span style={{ fontFamily: THEME.fonts.mono, fontSize: '11px', color: THEME.colors.textSecondary, maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={op.modelId}>
                  {op.modelId.split('/').pop()}
                </span>
                <span
                  style={{
                    fontFamily: THEME.fonts.mono,
                    fontSize: '11px',
                    color: op.score >= 8 ? THEME.colors.status.passed : THEME.colors.status.pending,
                    fontWeight: 600,
                  }}
                >
                  Score: {op.score}/10
                </span>
              </div>
              <span style={{ fontSize: '10px', textTransform: 'uppercase', color: THEME.colors.textTertiary, display: 'block', marginBottom: '8px' }}>
                Persona: {op.persona}
              </span>
              <p
                style={{
                  fontSize: '12px',
                  lineHeight: 1.5,
                  color: THEME.colors.textPrimary,
                  overflow: expandOpinions ? 'visible' : 'hidden',
                  textOverflow: 'ellipsis',
                  display: '-webkit-box',
                  WebkitLineClamp: expandOpinions ? 99 : 5,
                  WebkitBoxOrient: 'vertical',
                }}
              >
                {op.opinionText}
              </p>
            </div>
            
            {!expandOpinions && (
              <span
                style={{ fontSize: '11px', color: THEME.colors.accent, cursor: 'pointer', marginTop: '8px' }}
                onClick={() => setExpandOpinions(true)}
              >
                Read more...
              </span>
            )}
          </div>
        ))}
      </div>

      {/* STAGE 2: Anonymized Cross-Review Matrix */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <h3 style={{ fontSize: '13px', textTransform: 'uppercase', letterSpacing: '0.05em', color: THEME.colors.textSecondary, display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontFamily: THEME.fonts.mono, color: THEME.colors.accent }}>02</span>
          Stage 2: Anonymized Cross-Review Matrix
        </h3>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '11px', color: THEME.colors.textSecondary }}>Reveal Identities</span>
          <div
            onClick={() => {
              logUIAction('DeliberationView', 'toggle_reveal_identities', { nextState: !revealIdentities });
              setRevealIdentities(!revealIdentities);
            }}
            style={{
              width: '36px',
              height: '18px',
              borderRadius: '9px',
              backgroundColor: revealIdentities ? THEME.colors.accent : THEME.colors.surface3,
              border: THEME.borders.subtle,
              cursor: 'pointer',
              position: 'relative',
              transition: 'background-color 0.2s',
            }}
          >
            <div
              style={{
                width: '12px',
                height: '12px',
                borderRadius: '50%',
                backgroundColor: revealIdentities ? THEME.colors.background : THEME.colors.textSecondary,
                position: 'absolute',
                top: '2px',
                left: revealIdentities ? '20px' : '3px',
                transition: 'left 0.2s',
              }}
            />
          </div>
        </div>
      </div>

      {/* Critique matrix table */}
      <div className="dense-table-wrapper" style={{ marginBottom: '32px', border: THEME.borders.subtle }}>
        <table className="dense-table" style={{ tableLayout: 'fixed' }}>
          <thead>
            <tr>
              <th style={{ width: '150px' }}>Reviewer (Row) \ Reviewee (Col)</th>
              {verdict.model_lineup.map((_, idx) => (
                <th key={idx} style={{ textAlign: 'center' }}>
                  {revealIdentities ? (
                    <span style={{ fontFamily: THEME.fonts.mono, fontSize: '11px' }}>
                      {verdict.model_lineup[idx].split('/').pop()}
                    </span>
                  ) : (
                    getVoiceName(idx)
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {verdict.model_lineup.map((_, reviewerIdx) => {
              const reviewerVoice = getVoiceName(reviewerIdx);
              return (
                <tr key={reviewerIdx}>
                  <td style={{ fontWeight: 600, backgroundColor: THEME.colors.surface2 }}>
                    {revealIdentities ? (
                      <div style={{ display: 'flex', flexDirection: 'column' }}>
                        <span style={{ fontFamily: THEME.fonts.mono, fontSize: '11px' }}>
                          {verdict.model_lineup[reviewerIdx].split('/').pop()}
                        </span>
                        <span style={{ fontSize: '9px', color: THEME.colors.textTertiary, textTransform: 'uppercase' }}>
                          {verdict.persona_assignment[verdict.model_lineup[reviewerIdx]]}
                        </span>
                      </div>
                    ) : (
                      reviewerVoice
                    )}
                  </td>
                  {verdict.model_lineup.map((_, revieweeIdx) => {
                    if (reviewerIdx === revieweeIdx) {
                      return (
                        <td key={revieweeIdx} style={{ backgroundColor: '#0D0D0E', color: THEME.colors.textTertiary, textAlign: 'center', fontStyle: 'italic' }}>
                          Self-Ref
                        </td>
                      );
                    }
                    
                    const item = critiques.find((c) => c.reviewer === reviewerVoice && c.reviewee === getVoiceName(revieweeIdx));
                    const isExpanded = expandedCritique?.r === reviewerVoice && expandedCritique?.e === getVoiceName(revieweeIdx);

                    return (
                      <td
                        key={revieweeIdx}
                        onClick={() => {
                          if (item) {
                            setExpandedCritique(isExpanded ? null : { r: reviewerVoice, e: getVoiceName(revieweeIdx) });
                          }
                        }}
                        style={{
                          cursor: 'pointer',
                          backgroundColor: isExpanded ? THEME.colors.surface3 : 'transparent',
                          transition: 'background-color 0.15s',
                        }}
                      >
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '4px' }}>
                          <span style={{ fontFamily: THEME.fonts.mono, fontWeight: 600, color: (item?.scoreAssigned || 8) >= 7 ? THEME.colors.status.passed : THEME.colors.status.failed }}>
                            Score: {item?.scoreAssigned}/10
                          </span>
                          <span style={{ fontSize: '10px', color: THEME.colors.textTertiary, maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginTop: '2px' }}>
                            {item?.critiqueText}
                          </span>
                          {isExpanded && item && (
                            <div style={{ marginTop: '8px', padding: '6px', borderTop: THEME.borders.subtle, width: '100%', color: THEME.colors.textPrimary, whiteSpace: 'normal', fontSize: '11px' }}>
                              <strong>Critique text:</strong> "{item.critiqueText} The structural parameters seem underspecified, risking numerical convergence bounds."
                            </div>
                          )}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* STAGE 3: Chairman Synthesis with Preserved Dissent */}
      <h3 style={{ fontSize: '13px', textTransform: 'uppercase', letterSpacing: '0.05em', color: THEME.colors.textSecondary, marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ fontFamily: THEME.fonts.mono, color: THEME.colors.accent }}>03</span>
        Stage 3: Chairman Synthesis & Preserved Dissent
      </h3>

      <div className="council-verdict-grid">
        
        {/* Left Column: Chairman Majority view */}
        <div className="verdict-majority" style={{ borderRight: `1px solid ${THEME.colors.surface3}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <span style={{ fontSize: '18px' }}>👑</span>
            <div>
              <span style={{ fontSize: '12px', fontWeight: 600, display: 'block' }}>Chairman Consensus Synthesis</span>
              <span style={{ fontFamily: THEME.fonts.mono, fontSize: '10px', color: THEME.colors.textTertiary }}>{verdict.chairman_model}</span>
            </div>
          </div>
          
          <div
            className="surface-1"
            style={{
              padding: '16px',
              border: THEME.borders.subtle,
              lineHeight: 1.6,
              color: THEME.colors.textPrimary,
              fontSize: '13px',
              fontFamily: THEME.fonts.sans
            }}
          >
            <p style={{ marginBottom: '12px' }}>{verdict.majority_view}</p>
            <p style={{ color: THEME.colors.textSecondary }}>
              Consensus summary: The council generally agrees on the theoretical worthiness of the hypothesis spec. Convergence constraints are defined cleanly. However, to account for minority reservations, the approval is qualified under the condition that initial G3 surrogate testing does not violate the force balance convergence limits.
            </p>
          </div>
        </div>

        {/* Right Column: Preserved Dissents */}
        <div className="verdict-dissents">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: THEME.colors.status.dissent }} />
            <span style={{ fontSize: '12px', fontWeight: 600 }}>
              Preserved Dissents ({verdict.preserved_dissents.length})
            </span>
          </div>

          {verdict.preserved_dissents.length === 0 ? (
            <div
              className="surface-1"
              style={{
                padding: '16px',
                border: `1px solid ${THEME.colors.status.pending}4D`,
                backgroundColor: THEME.colors.alpha.pending,
                color: THEME.colors.status.pending,
                fontSize: '12px',
                fontFamily: THEME.fonts.mono
              }}
            >
              No dissent recorded — flag for sycophancy review.
            </div>
          ) : (
            verdict.preserved_dissents.map((dissent, idx) => (
              <div
                key={idx}
                className="dissent-card"
                style={{
                  backgroundColor: THEME.colors.alpha.dissent,
                  border: `1px solid ${THEME.colors.status.dissent}3D`,
                  borderLeft: `4px solid ${THEME.colors.status.dissent}`,
                  borderRadius: THEME.radius.card,
                  padding: '14px',
                  marginBottom: '12px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <span style={{ fontFamily: THEME.fonts.mono, fontSize: '11px', color: THEME.colors.textPrimary, fontWeight: 600 }}>
                    {dissent.model_id.split('/').pop()}
                  </span>
                  <span
                    style={{
                      fontFamily: THEME.fonts.mono,
                      fontSize: '10px',
                      color: THEME.colors.status.dissent,
                      textTransform: 'uppercase',
                      backgroundColor: 'rgba(167, 139, 250, 0.15)',
                      padding: '1px 5px',
                      borderRadius: '2px',
                    }}
                  >
                    {dissent.persona}
                  </span>
                </div>
                <h5 style={{ fontSize: '12px', fontWeight: 600, color: THEME.colors.status.dissent, marginBottom: '6px' }}>
                  View: {dissent.view}
                </h5>
                <p style={{ margin: 0, fontSize: '12px', lineHeight: 1.5, color: THEME.colors.textSecondary }}>
                  "{dissent.rationale}"
                </p>
              </div>
            ))
          )}
        </div>

      </div>

      {/* Bottom Metadata Strip */}
      <div
        className="surface-1"
        style={{
          marginTop: '32px',
          padding: '12px 18px',
          border: THEME.borders.subtle,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontSize: '11px',
          color: THEME.colors.textSecondary,
          fontFamily: THEME.fonts.mono
        }}
      >
        <span>Deliberation Cost: ${verdict.total_cost_usd.toFixed(4)}</span>
        <span>Wall Clock: {verdict.wall_clock_seconds.toFixed(2)}s</span>
        <span>Session ID: {verdict.session_id}</span>
        <span>Downstream Artifact: <a href={`/api/reports/${verdict.provenance_hash}`} style={{ color: THEME.colors.accent }}>RunReport ({verdict.provenance_hash.substring(0, 7)})</a></span>
      </div>

    </div>
  );
};
