/**
 * @file Settings.tsx
 * @description Operational configuration panel for the AI Co-Computational Physicist Factory.
 * Manages dollar-burn limits (daily and aggregate budget caps) and LLM model lineups.
 *
 * Use Cases:
 * 1. Setting and saving daily caps to prevent run-away api cost spend.
 * 2. Tuning Council persona assignments (Visionary / Pessimist / Pragmatist) for diverse deliberation.
 * 3. Toggling specific models on/off and monitoring token rate limit parameters.
 * 4. Preventing sycophancy or weak consensus warnings by maintaining at least 3 active models.
 */

import React, { useState, useEffect } from 'react';
import { THEME, logUIAction } from '../components/theme';

// Types aligning with the Pydantic SettingsResponse
export interface ModelConfig {
  model_id: string;
  persona: 'visionary' | 'pessimist' | 'pragmatist';
  enabled: boolean;
}

export interface SettingsData {
  stale: boolean;
  served_at: string;
  budgets: {
    aggregate_cap_usd: number;
    aggregate_burn_usd: number;
    daily_cap_usd: number;
    daily_burn_usd: number;
    per_hypothesis_cap_usd: number;
  };
  rate_limits: {
    tokens_per_minute: number;
    requests_per_minute: number;
  };
  active_lineup: ModelConfig[];
}

/**
 * Renders a loading skeleton for Settings view.
 */
const SettingsSkeleton: React.FC = () => {
  return (
    <div style={{ padding: '24px', backgroundColor: THEME.colors.background, minHeight: '100vh', color: THEME.colors.textPrimary }}>
      <div style={{ width: '150px', height: '20px', backgroundColor: '#222226', borderRadius: '2px', marginBottom: '24px' }} />
      
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', marginBottom: '24px' }}>
        <div className="surface-1" style={{ height: '220px', padding: '16px' }}>
          <div style={{ width: '120px', height: '14px', backgroundColor: '#222226', borderRadius: '2px', marginBottom: '16px' }} />
          {[1, 2, 3].map((i) => (
            <div key={i} style={{ width: '80%', height: '12px', backgroundColor: '#222226', borderRadius: '2px', marginBottom: '12px' }} />
          ))}
        </div>
        <div className="surface-1" style={{ height: '220px', padding: '16px' }}>
          <div style={{ width: '120px', height: '14px', backgroundColor: '#222226', borderRadius: '2px', marginBottom: '16px' }} />
          {[1, 2, 3].map((i) => (
            <div key={i} style={{ width: '80%', height: '12px', backgroundColor: '#222226', borderRadius: '2px', marginBottom: '12px' }} />
          ))}
        </div>
      </div>
    </div>
  );
};

/**
 * Settings View component.
 * Allows operators to calibrate budget caps and multi-LLM lineups.
 */
export const Settings: React.FC = () => {
  const [data, setData] = useState<SettingsData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Form states mapping local edits before saving
  const [dailyCap, setDailyCap] = useState<number>(100);
  const [aggregateCap, setAggregateCap] = useState<number>(1000);
  const [perHypothesisCap, setPerHypothesisCap] = useState<number>(50);
  const [lineup, setLineup] = useState<ModelConfig[]>([]);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [saveSuccess, setSaveSuccess] = useState<boolean>(false);

  // Fetch settings parameters on mount
  useEffect(() => {
    let active = true;
    logUIAction('Settings', 'useEffect[mount]', {});

    async function fetchSettings() {
      try {
        const response = await fetch('/api/settings');
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        const json: SettingsData = await response.json();
        if (active) {
          setData(json);
          setDailyCap(json.budgets.daily_cap_usd);
          setAggregateCap(json.budgets.aggregate_cap_usd);
          setPerHypothesisCap(json.budgets.per_hypothesis_cap_usd || 50);
          setLineup(json.active_lineup || []);
          setLoading(false);
        }
      } catch (err) {
        logUIAction('Settings', 'fetchError', { error: String(err) });
        if (active) {
          setError(String(err));
          setLoading(false);
        }
      }
    }

    fetchSettings();
    return () => {
      active = false;
    };
  }, []);

  /**
   * Toggles the active/enabled state of a model inside the council lineup.
   * @param modelId Target model identifier
   */
  const handleToggleModel = (modelId: string) => {
    const updatedLineup = lineup.map((model) => {
      if (model.model_id === modelId) {
        const nextVal = !model.enabled;
        logUIAction('Settings', 'handleToggleModel', { modelId, nextState: nextVal });
        return { ...model, enabled: nextVal };
      }
      return model;
    });
    setLineup(updatedLineup);
  };

  /**
   * Modifies the assigned persona for a specific LLM candidate.
   * @param modelId Target model identifier
   * @param persona Selected persona ('visionary' | 'pessimist' | 'pragmatist')
   */
  const handlePersonaChange = (modelId: string, persona: 'visionary' | 'pessimist' | 'pragmatist') => {
    logUIAction('Settings', 'handlePersonaChange', { modelId, newPersona: persona });
    const updatedLineup = lineup.map((model) => {
      if (model.model_id === modelId) {
        return { ...model, persona };
      }
      return model;
    });
    setLineup(updatedLineup);
  };

  /**
   * Commits budget edits and lineup calibrations to local state.
   * Emulates API configuration save action.
   */
  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!data) return;

    logUIAction('Settings', 'handleSaveSettings', {
      dailyCap,
      aggregateCap,
      perHypothesisCap,
      activeModelsCount: lineup.filter((m) => m.enabled).length,
    });
    setIsSaving(true);

    try {
      // Emulate API save latency
      await new Promise((resolve) => setTimeout(resolve, 800));
      
      setData((prev) => {
        if (!prev) return null;
        return {
          ...prev,
          budgets: {
            ...prev.budgets,
            daily_cap_usd: dailyCap,
            aggregate_cap_usd: aggregateCap,
            per_hypothesis_cap_usd: perHypothesisCap,
          },
          active_lineup: lineup,
        };
      });

      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      console.error('Error saving settings:', err);
    } finally {
      setIsSaving(false);
    }
  };

  if (loading) {
    return <SettingsSkeleton />;
  }

  if (error) {
    return (
      <div style={{ padding: '40px', backgroundColor: THEME.colors.background, minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="surface-1" style={{ padding: '24px', maxWidth: '500px', width: '100%' }}>
          <h3 style={{ color: THEME.colors.status.failed, marginBottom: '12px' }}>Settings Calibration Failure</h3>
          <p style={{ color: THEME.colors.textSecondary, marginBottom: '20px', fontFamily: THEME.fonts.mono }}>{error}</p>
          <button className="btn btn-secondary" onClick={() => window.location.reload()}>Retry handshake</button>
        </div>
      </div>
    );
  }

  const activeModelsCount = lineup.filter((m) => m.enabled).length;
  const isConsensusWeak = activeModelsCount < 3;

  return (
    <div style={{ backgroundColor: THEME.colors.background, minHeight: '100vh', padding: '24px', color: THEME.colors.textPrimary }}>
      
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <div>
          <h2 style={{ fontSize: '20px', fontWeight: 600 }}>System Configurations & Calibration</h2>
          <p style={{ fontSize: '12px', color: THEME.colors.textSecondary }}>
            Configure computational quotas, budget limits, and Council debate parameters.
          </p>
        </div>
        
        {saveSuccess && (
          <span style={{ color: THEME.colors.status.passed, fontSize: '12px', fontWeight: 600, fontFamily: THEME.fonts.mono }}>
            ✓ Configuration saved successfully
          </span>
        )}
      </div>

      <form onSubmit={handleSaveSettings}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', marginBottom: '24px', alignItems: 'stretch' }}>
          
          {/* Section 1: Financial & Quota Budgets */}
          <div className="surface-1" style={{ padding: '20px', border: THEME.borders.subtle, display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
            <div>
              <h3 style={{ fontSize: '13px', textTransform: 'uppercase', color: THEME.colors.textSecondary, marginBottom: '16px', letterSpacing: '0.05em' }}>
                Resource Budgets
              </h3>

              {/* Today's Burn Visual meter */}
              <div style={{ marginBottom: '20px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: THEME.colors.textSecondary, marginBottom: '4px' }}>
                  <span>Today's Burn Quota</span>
                  <span style={{ fontFamily: THEME.fonts.mono }}>
                    ${data?.budgets.daily_burn_usd.toFixed(2)} / ${dailyCap}
                  </span>
                </div>
                <div style={{ width: '100%', height: '6px', backgroundColor: THEME.colors.surface3, borderRadius: '3px', overflow: 'hidden' }}>
                  <div
                    style={{
                      height: '100%',
                      width: `${Math.min(100, ((data?.budgets.daily_burn_usd || 0) / dailyCap) * 100)}%`,
                      backgroundColor: THEME.colors.accent,
                      transition: 'width 0.3s ease'
                    }}
                  />
                </div>
              </div>

              {/* Fields */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', color: THEME.colors.textTertiary, marginBottom: '4px', textTransform: 'uppercase' }}>
                    Daily Cost Cap (USD)
                  </label>
                  <input
                    type="number"
                    required
                    min={1}
                    className="form-input font-mono"
                    value={dailyCap}
                    onChange={(e) => setDailyCap(parseFloat(e.target.value) || 0)}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', color: THEME.colors.textTertiary, marginBottom: '4px', textTransform: 'uppercase' }}>
                    Aggregate Program Cap (USD)
                  </label>
                  <input
                    type="number"
                    required
                    min={1}
                    className="form-input font-mono"
                    value={aggregateCap}
                    onChange={(e) => setAggregateCap(parseFloat(e.target.value) || 0)}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', color: THEME.colors.textTertiary, marginBottom: '4px', textTransform: 'uppercase' }}>
                    Max cost per Hypothesis spec (USD)
                  </label>
                  <input
                    type="number"
                    required
                    min={1}
                    className="form-input font-mono"
                    value={perHypothesisCap}
                    onChange={(e) => setPerHypothesisCap(parseFloat(e.target.value) || 0)}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Section 2: Quota & Token Rate Limits */}
          <div className="surface-1" style={{ padding: '20px', border: THEME.borders.subtle }}>
            <h3 style={{ fontSize: '13px', textTransform: 'uppercase', color: THEME.colors.textSecondary, marginBottom: '16px', letterSpacing: '0.05em' }}>
              API Daemon Rate Limits
            </h3>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <span style={{ fontSize: '11px', color: THEME.colors.textTertiary, display: 'block', textTransform: 'uppercase' }}>Tokens Per Minute Limit</span>
                <span style={{ fontFamily: THEME.fonts.mono, fontSize: '18px', fontWeight: 600, color: THEME.colors.textPrimary }}>
                  {data?.rate_limits.tokens_per_minute.toLocaleString() || '80,000'} TPM
                </span>
                <span style={{ display: 'block', fontSize: '11px', color: THEME.colors.textSecondary, marginTop: '2px' }}>
                  Globally allocated quota across enabled providers.
                </span>
              </div>

              <div>
                <span style={{ fontSize: '11px', color: THEME.colors.textTertiary, display: 'block', textTransform: 'uppercase' }}>Requests Per Minute Limit</span>
                <span style={{ fontFamily: THEME.fonts.mono, fontSize: '18px', fontWeight: 600, color: THEME.colors.textPrimary }}>
                  {data?.rate_limits.requests_per_minute.toLocaleString() || '200'} RPM
                </span>
                <span style={{ display: 'block', fontSize: '11px', color: THEME.colors.textSecondary, marginTop: '2px' }}>
                  Aggregated requests bucket for parallel cross-critique threads.
                </span>
              </div>

              <div style={{ borderTop: `1px solid ${THEME.colors.surface3}`, paddingTop: '12px', fontSize: '11px', color: THEME.colors.textSecondary }}>
                <strong>Hardware context:</strong> GPU nodes are shared. Exceeding limits will trigger automatic backing-off and schedule delay.
              </div>
            </div>
          </div>

        </div>

        {/* Section 3: LLM Deliberation Lineup */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <h3 style={{ fontSize: '13px', textTransform: 'uppercase', color: THEME.colors.textSecondary, letterSpacing: '0.05em' }}>
            Multi-LLM Deliberation Council Lineup
          </h3>
          
          <span style={{ fontSize: '11px', color: THEME.colors.textSecondary, fontFamily: THEME.fonts.mono }}>
            Active Models: {activeModelsCount}
          </span>
        </div>

        {/* Sycophancy warning banner */}
        {isConsensusWeak && (
          <div
            style={{
              padding: '12px 16px',
              backgroundColor: THEME.colors.alpha.pending,
              border: `1px solid ${THEME.colors.status.pending}4D`,
              borderRadius: THEME.radius.card,
              color: THEME.colors.status.pending,
              fontSize: '12px',
              marginBottom: '16px',
              lineHeight: 1.4
            }}
          >
            <strong>⚠ Weak Consensus Threat:</strong> Enabling fewer than 3 models disables robust multi-persona cross-critique, significantly increasing sycophancy risk and reducing the worthiness screening fidelity at Gate G2. Enforce at least 3 models.
          </div>
        )}

        <div className="dense-table-wrapper" style={{ marginBottom: '24px', border: THEME.borders.subtle }}>
          <table className="dense-table">
            <thead>
              <tr>
                <th style={{ width: '400px' }}>Model ID</th>
                <th>Assigned Council Persona</th>
                <th style={{ width: '150px', textAlign: 'center' }}>Active Status</th>
              </tr>
            </thead>
            <tbody>
              {lineup.map((model) => (
                <tr key={model.model_id}>
                  <td style={{ fontFamily: THEME.fonts.mono, fontWeight: 600 }}>{model.model_id}</td>
                  <td>
                    <select
                      className="form-input"
                      style={{ padding: '3px 8px', width: '150px', backgroundColor: THEME.colors.surface3, border: THEME.borders.subtle }}
                      value={model.persona}
                      onChange={(e) => handlePersonaChange(model.model_id, e.target.value as any)}
                    >
                      <option value="visionary">Visionary</option>
                      <option value="pessimist">Pessimist</option>
                      <option value="pragmatist">Pragmatist</option>
                    </select>
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <input
                      type="checkbox"
                      checked={model.enabled}
                      onChange={() => handleToggleModel(model.model_id)}
                      style={{ width: '16px', height: '16px', cursor: 'pointer' }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Submit action */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => window.location.reload()}
          >
            Reset Form
          </button>
          <button
            type="submit"
            disabled={isSaving}
            className="btn btn-primary"
            style={{ width: '150px' }}
          >
            {isSaving ? 'Saving Configurations...' : 'Save Configuration'}
          </button>
        </div>

      </form>
    </div>
  );
};
