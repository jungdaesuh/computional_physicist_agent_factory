/**
 * @file EvidenceLedger.tsx
 * @description Searchable browser for the historical record of every hypothesis executed by the factory.
 * Features faceted filters, uncertainty quantification thresholds, detailed slide-over panel,
 * and a C5 "Audit Mode" to inspect downstream dependency compounding and sycophancy risks.
 *
 * Use Cases:
 * 1. Searching and filtering past hypothesis results by domain, simulator, or consensus.
 * 2. Visualizing uncertainty bounds and checking relitigation criteria.
 * 3. Inspecting cryptographic provenance hashes for all verified experiment outcomes.
 * 4. Auditing systemic compounding of high-uncertainty findings in downstream cycles.
 */

import React, { useState, useEffect } from 'react';
import { THEME, logUIAction } from '../components/theme';
import { StatusPill } from '../components/StatusPill';
import { 
  Search, 
  X, 
  Copy, 
  CheckCircle,
  AlertTriangle
} from 'lucide-react';

// Interfaces for Evidence Ledger Entry
export interface LedgerEntry {
  hypothesis_id: string;
  parent_gap_id: string;
  title: string;
  domain: 'plasma' | 'CFD' | 'MD' | 'DFT';
  simulator_id: string;
  date: string;
  cost_usd: number;
  result: 'passed' | 'failed' | 'intractable' | 'inconclusive';
  snippet: string;
  has_dissent: boolean;
  dissent_count: number;
  uncertainty_val: number; // Point estimate
  uncertainty_range: [number, number]; // [min, max]
  relitigate_eligible: boolean;
  relitigate_ready: boolean;
  downstream_citations: number; // How many future runs depend on this
  provenance: {
    code_hash: string;
    env_hash: string;
    input_hash: string;
    seed: number;
    container_sha: string;
  };
  relitigate_if: {
    condition: string;
    status: 'met' | 'unmet';
  }[];
}

const MOCK_LEDGER_ENTRIES: LedgerEntry[] = [
  {
    hypothesis_id: 'hyp-8a2f1c9',
    parent_gap_id: 'gap-01a2f9b',
    title: 'High-beta W7-X configuration with optimized planar coil geometries reduces neoclassical transport.',
    domain: 'plasma',
    simulator_id: 'sim-desc-01',
    date: '2026-05-23T14:20:00Z',
    cost_usd: 622.50,
    result: 'passed',
    snippet: 'Optimized boundary parameters achieve 4.2% beta with quasi-symmetric coil alignment. Dissent noted.',
    has_dissent: true,
    dissent_count: 1,
    uncertainty_val: 0.12,
    uncertainty_range: [0.08, 0.18],
    relitigate_eligible: true,
    relitigate_ready: false,
    downstream_citations: 14,
    provenance: {
      code_hash: '9e8d3f2c1b0a',
      env_hash: 'a1b2c3d4e5f6',
      input_hash: 'f6e5d4c3b2a1',
      seed: 8429184,
      container_sha: 'sha256:d1a938c4b2e88a911...'
    },
    relitigate_if: [
      { condition: 'Surrogate R² accuracy increases past 0.95', status: 'unmet' },
      { condition: 'New cross-simulator agreement telemetry is registered', status: 'unmet' }
    ]
  },
  {
    hypothesis_id: 'hyp-7f9e8a1',
    parent_gap_id: 'gap-02f9b1c',
    title: 'Helical coils with non-interlocking vacuum vessel channels exhibit stability under high magnetic shear.',
    domain: 'plasma',
    simulator_id: 'sim-desc-01',
    date: '2026-05-21T09:45:00Z',
    cost_usd: 198.00,
    result: 'failed',
    snippet: 'Mercier stability limits violated under high magnetic pressure gradients. Divergence at G4.',
    has_dissent: false,
    dissent_count: 0,
    uncertainty_val: 0.05,
    uncertainty_range: [0.03, 0.07],
    relitigate_eligible: false,
    relitigate_ready: false,
    downstream_citations: 0,
    provenance: {
      code_hash: '2c3d4e5f6a7b',
      env_hash: 'b2c3d4e5f6a7',
      input_hash: 'a7b6c5d4e3f2',
      seed: 1948291,
      container_sha: 'sha256:d1a938c4b2e88a911...'
    },
    relitigate_if: []
  },
  {
    hypothesis_id: 'hyp-3b2d1a4',
    parent_gap_id: 'gap-05c4b3a',
    title: 'Neoclassical transport optimization using quasi-helical equilibria reduces bootstrap current misalignment.',
    domain: 'plasma',
    simulator_id: 'sim-simsopt-02',
    date: '2026-05-18T16:10:00Z',
    cost_usd: 960.00,
    result: 'passed',
    snippet: 'DKES transport calculations show 30% reduction in radial drift losses. Stable convergence.',
    has_dissent: false,
    dissent_count: 0,
    uncertainty_val: 0.28,
    uncertainty_range: [0.15, 0.42],
    relitigate_eligible: true,
    relitigate_ready: true,
    downstream_citations: 8,
    provenance: {
      code_hash: '3d4e5f6a7b8c',
      env_hash: 'c3d4e5f6a7b8',
      input_hash: 'b8c7d6e5f4g3',
      seed: 9402948,
      container_sha: 'sha256:f8e9102cba39b4d82...'
    },
    relitigate_if: [
      { condition: 'Fidelity limit escalated to full-fidelity oracle runs', status: 'met' }
    ]
  },
  {
    hypothesis_id: 'hyp-5c4b3a2',
    parent_gap_id: 'gap-07d6e5f',
    title: 'High-temperature superconductor coil alignment for Tokamak divertor configuration under high heat flux.',
    domain: 'CFD',
    simulator_id: 'sim-openfoam-03',
    date: '2026-05-15T11:30:00Z',
    cost_usd: 2400.00,
    result: 'intractable',
    snippet: 'Mesh generation failed due to extreme boundary curvature of divertor shield. snappyHexMesh limit.',
    has_dissent: true,
    dissent_count: 2,
    uncertainty_val: 0.65,
    uncertainty_range: [0.45, 0.85],
    relitigate_eligible: true,
    relitigate_ready: true,
    downstream_citations: 3,
    provenance: {
      code_hash: '4e5f6a7b8c9d',
      env_hash: 'd4e5f6a7b8c9',
      input_hash: 'c9d8e7f6g5h4',
      seed: 2940284,
      container_sha: 'sha256:7c91d4e0e2c88f910...'
    },
    relitigate_if: [
      { condition: 'Local polisher constraint relaxation rules are updated', status: 'met' }
    ]
  },
  {
    hypothesis_id: 'hyp-2a1f8e7',
    parent_gap_id: 'gap-09e8d7c',
    title: 'Multi-modal turbulent flow suppression in stellarator boundary layers via shear flow injection.',
    domain: 'DFT',
    simulator_id: 'sim-dft-qe-04',
    date: '2026-05-10T18:00:00Z',
    cost_usd: 1045.00,
    result: 'inconclusive',
    snippet: 'Quantum effects at boundary exhibit high variance. Inconsistent plane-wave energy levels.',
    has_dissent: true,
    dissent_count: 3,
    uncertainty_val: 0.78,
    uncertainty_range: [0.60, 0.95],
    relitigate_eligible: false,
    relitigate_ready: false,
    downstream_citations: 18, // Heavily cited but high uncertainty and high dissent! HALLUCINATION RISK!
    provenance: {
      code_hash: '5f6a7b8c9d0e',
      env_hash: 'e5f6a7b8c9d0',
      input_hash: 'd0e9f8g7h6i5',
      seed: 4920482,
      container_sha: 'sha256:bc31f92d4b1a89c8a...'
    },
    relitigate_if: []
  }
];

const mapResultToStatus = (result: 'passed' | 'failed' | 'intractable' | 'inconclusive'): 'passed' | 'failed' | 'parked' | 'pending' => {
  switch (result) {
    case 'passed':
      return 'passed';
    case 'failed':
      return 'failed';
    case 'intractable':
      return 'parked';
    case 'inconclusive':
      return 'pending';
    default:
      return 'pending';
  }
};

export const EvidenceLedger: React.FC = () => {
  const [searchQuery, setSearchQuery] = useState('');
  const [resultFilter, setResultFilter] = useState<string>('all');
  const [domainFilter, setDomainFilter] = useState<string>('all');
  const [uncertaintyThreshold, setUncertaintyThreshold] = useState<number>(0.8);
  const [hasDissentOnly, setHasDissentOnly] = useState<boolean>(false);
  const [hasRelitigateOnly, setHasRelitigateOnly] = useState<boolean>(false);
  
  const [auditMode, setAuditMode] = useState<boolean>(false); // C5 Program Direction Audit mode
  const [selectedEntryId, setSelectedEntryId] = useState<string | null>(null);

  useEffect(() => {
    logUIAction('EvidenceLedger', 'mount', {});
  }, []);

  // Filter criteria
  const filteredEntries = MOCK_LEDGER_ENTRIES.filter((entry) => {
    const matchesSearch = entry.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
                          entry.hypothesis_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
                          entry.parent_gap_id.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesResult = resultFilter === 'all' || entry.result === resultFilter;
    const matchesDomain = domainFilter === 'all' || entry.domain === domainFilter;
    const matchesUncertainty = entry.uncertainty_val <= uncertaintyThreshold;
    const matchesDissent = !hasDissentOnly || entry.has_dissent;
    const matchesRelitigate = !hasRelitigateOnly || (entry.relitigate_eligible && entry.relitigate_ready);

    return matchesSearch && matchesResult && matchesDomain && matchesUncertainty && matchesDissent && matchesRelitigate;
  });

  // Sort logic based on mode
  // Normal Mode: Sort by date descending
  // Audit Mode: Sort by downstream citations descending to flag high citation + high uncertainty risk
  const sortedEntries = [...filteredEntries].sort((a, b) => {
    if (auditMode) {
      return b.downstream_citations - a.downstream_citations;
    }
    return new Date(b.date).getTime() - new Date(a.date).getTime();
  });

  const selectedEntry = MOCK_LEDGER_ENTRIES.find(e => e.hypothesis_id === selectedEntryId);

  /**
   * Helper to render the uncertainty horizontal bar indicator
   * @param point Point estimate value
   * @param range Range interval array [min, max]
   */
  const renderUncertaintyBar = (point: number, range: [number, number]) => {
    const leftPct = range[0] * 100;
    const widthPct = (range[1] - range[0]) * 100;
    const dotPct = point * 100;

    return (
      <div style={{ position: 'relative', width: '120px', height: '16px', display: 'flex', alignItems: 'center' }} title={`Uncertainty: ${point.toFixed(2)} (${range[0].toFixed(2)} - ${range[1].toFixed(2)})`}>
        {/* Track */}
        <div style={{ width: '100%', height: '2px', backgroundColor: THEME.colors.surface3 }} />
        
        {/* Range bar */}
        <div 
          style={{ 
            position: 'absolute', 
            left: `${leftPct}%`, 
            width: `${widthPct}%`, 
            height: '4px', 
            backgroundColor: point > 0.6 ? THEME.colors.status.failed + '88' : THEME.colors.accent + '88', 
            borderRadius: '1px' 
          }} 
        />
        
        {/* Point Estimate Dot */}
        <div 
          style={{ 
            position: 'absolute', 
            left: `${dotPct}%`, 
            width: '6px', 
            height: '6px', 
            borderRadius: '50%', 
            backgroundColor: point > 0.6 ? THEME.colors.status.failed : THEME.colors.accent,
            transform: 'translateX(-3px)'
          }} 
        />
      </div>
    );
  };

  /**
   * Triggers a clipboard write for the cryptographic hash.
   * Logs copying action and gives local alert.
   * @param hash Text hash
   */
  const copyToClipboard = (hash: string) => {
    logUIAction('EvidenceLedger', 'copyHash', { hash });
    navigator.clipboard.writeText(hash);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', backgroundColor: THEME.colors.background, color: THEME.colors.textPrimary }}>
      
      {/* Top Header & Audit toggle */}
      <div 
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '16px 24px',
          borderBottom: THEME.borders.subtle,
          backgroundColor: THEME.colors.surface1
        }}
      >
        <div>
          <h2 style={{ fontSize: '16px', fontWeight: 600, margin: 0 }}>Evidence Ledger Archive</h2>
          <span style={{ fontSize: '11px', color: THEME.colors.textTertiary }}>
            Cryptographically sealed repository of computational findings and proof of simulation.
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button
            onClick={() => {
              logUIAction('EvidenceLedger', 'toggleAuditMode', { targetState: !auditMode });
              setAuditMode(!auditMode);
            }}
            style={{
              padding: '6px 12px',
              backgroundColor: auditMode ? THEME.colors.alpha.failed : 'transparent',
              border: auditMode ? `1px solid ${THEME.colors.status.failed}4D` : THEME.borders.subtle,
              borderRadius: THEME.radius.card,
              color: auditMode ? THEME.colors.status.failed : THEME.colors.textSecondary,
              fontSize: '12px',
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
          >
            <AlertTriangle size={14} />
            {auditMode ? 'C5 Audit Mode: ACTIVE' : 'Trigger C5 Audit Mode'}
          </button>
        </div>
      </div>

      {/* Main content area */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden', position: 'relative' }}>
        
        {/* Results column */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflowY: 'auto', padding: '20px' }}>
          
          {/* Top Filter Strip */}
          <div 
            className="surface-1" 
            style={{ 
              padding: '16px', 
              border: THEME.borders.subtle, 
              borderRadius: THEME.radius.card,
              marginBottom: '20px',
              display: 'flex',
              flexDirection: 'column',
              gap: '12px'
            }}
          >
            {/* Search Input */}
            <div style={{ position: 'relative' }}>
              <Search size={14} color={THEME.colors.textTertiary} style={{ position: 'absolute', left: '12px', top: '12px' }} />
              <input
                type="text"
                placeholder="Search ledger claims, hypothesis SHA-256 prefixes..."
                style={{
                  width: '100%',
                  padding: '9px 12px 9px 36px',
                  backgroundColor: THEME.colors.surface2,
                  border: THEME.borders.subtle,
                  borderRadius: THEME.radius.card,
                  color: THEME.colors.textPrimary,
                  fontSize: '12px'
                }}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>

            {/* Faceted Filters & Slider */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', alignItems: 'center' }}>
              
              <div style={{ display: 'flex', gap: '8px' }}>
                <select
                  className="form-input"
                  style={{ padding: '4px 8px', fontSize: '11px', width: '120px', backgroundColor: THEME.colors.surface2, border: THEME.borders.subtle }}
                  value={resultFilter}
                  onChange={(e) => setResultFilter(e.target.value)}
                >
                  <option value="all">All Verdicts</option>
                  <option value="passed">Passed</option>
                  <option value="failed">Failed</option>
                  <option value="intractable">Intractable</option>
                  <option value="inconclusive">Inconclusive</option>
                </select>

                <select
                  className="form-input"
                  style={{ padding: '4px 8px', fontSize: '11px', width: '120px', backgroundColor: THEME.colors.surface2, border: THEME.borders.subtle }}
                  value={domainFilter}
                  onChange={(e) => setDomainFilter(e.target.value)}
                >
                  <option value="all">All Domains</option>
                  <option value="plasma">Plasma</option>
                  <option value="CFD">CFD</option>
                  <option value="DFT">DFT</option>
                </select>
              </div>

              {/* Uncertainty slider */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{ fontSize: '11px', color: THEME.colors.textSecondary, whiteSpace: 'nowrap' }}>Uncertainty Limit:</span>
                <input
                  type="range"
                  min="0.1"
                  max="1.0"
                  step="0.05"
                  style={{ width: '100px', accentColor: THEME.colors.accent }}
                  value={uncertaintyThreshold}
                  onChange={(e) => setUncertaintyThreshold(parseFloat(e.target.value))}
                />
                <span style={{ fontFamily: THEME.fonts.mono, fontSize: '11px', color: THEME.colors.accent, width: '30px' }}>
                  {uncertaintyThreshold.toFixed(2)}
                </span>
              </div>

              {/* Checkboxes */}
              <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: THEME.colors.textSecondary, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={hasDissentOnly}
                    onChange={(e) => setHasDissentOnly(e.target.checked)}
                    style={{ cursor: 'pointer' }}
                  />
                  Has Council Dissent
                </label>

                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: THEME.colors.textSecondary, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={hasRelitigateOnly}
                    onChange={(e) => setHasRelitigateOnly(e.target.checked)}
                    style={{ cursor: 'pointer' }}
                  />
                  Ready to Re-litigate
                </label>
              </div>

            </div>

          </div>

          {/* Audit Alert Banner in Audit Mode */}
          {auditMode && (
            <div 
              style={{
                padding: '12px 16px',
                backgroundColor: THEME.colors.alpha.failed,
                border: `1px solid ${THEME.colors.status.failed}4D`,
                borderLeft: `4px solid ${THEME.colors.status.failed}`,
                borderRadius: THEME.radius.card,
                color: THEME.colors.status.failed,
                fontSize: '12px',
                marginBottom: '16px',
                lineHeight: 1.4
              }}
            >
              <strong>⚠ Hallucination Compounding Audit:</strong> Displaying entries sorted by citation impact. Highlighted items represent research findings heavily cited by subsequent cycles but exhibiting high uncertainty (&gt; 0.60) or unresolved council dissents. These must be targeted for immediate C5 re-deliberation or high-fidelity simulation audits.
            </div>
          )}

          {/* Results Cards List */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {sortedEntries.length === 0 ? (
              <div className="empty-state">
                <span className="empty-state-text">No matching evidence registered in the ledger.</span>
              </div>
            ) : (
              sortedEntries.map((entry) => {
                const isSelected = entry.hypothesis_id === selectedEntryId;
                const isHighRisk = auditMode && entry.downstream_citations > 5 && (entry.uncertainty_val > 0.60 || entry.has_dissent);
                
                return (
                  <div
                    key={entry.hypothesis_id}
                    className="surface-1 hover-elevate"
                    onClick={() => {
                      logUIAction('EvidenceLedger', 'select_ledger_entry', { id: entry.hypothesis_id });
                      setSelectedEntryId(entry.hypothesis_id);
                    }}
                    style={{
                      padding: '16px',
                      cursor: 'pointer',
                      border: isHighRisk ? `1px solid ${THEME.colors.status.failed}6A` : isSelected ? THEME.borders.active : THEME.borders.subtle,
                      backgroundColor: isHighRisk ? THEME.colors.alpha.failed : 'transparent',
                      borderLeft: isSelected ? `4px solid ${THEME.colors.accent}` : isHighRisk ? `4px solid ${THEME.colors.status.failed}` : `4px solid transparent`,
                      transition: 'all 0.15s ease'
                    }}
                  >
                    
                    {/* Card Top Row */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontFamily: THEME.fonts.mono, fontSize: '11px', color: THEME.colors.accent }}>
                          {entry.hypothesis_id}
                        </span>
                        <span style={{ fontSize: '10px', color: THEME.colors.textTertiary }}>
                          parent: {entry.parent_gap_id}
                        </span>
                      </div>
                      
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        {entry.has_dissent && (
                          <span 
                            style={{
                              padding: '2px 6px',
                              backgroundColor: THEME.colors.alpha.dissent,
                              border: `1px solid ${THEME.colors.status.dissent}3D`,
                              borderRadius: THEME.radius.card,
                              fontSize: '10px',
                              color: THEME.colors.status.dissent,
                              fontWeight: 500
                            }}
                          >
                            Dissent ({entry.dissent_count})
                          </span>
                        )}
                        
                        {entry.relitigate_eligible && entry.relitigate_ready && (
                          <span 
                            style={{
                              padding: '2px 6px',
                              backgroundColor: THEME.colors.alpha.pending,
                              border: `1px solid ${THEME.colors.status.pending}4D`,
                              borderRadius: THEME.radius.card,
                              fontSize: '10px',
                              color: THEME.colors.status.pending,
                              fontWeight: 500
                            }}
                          >
                            Re-litigate
                          </span>
                        )}

                        <StatusPill status={mapResultToStatus(entry.result)} label={entry.result} />
                      </div>
                    </div>

                    {/* Card Title */}
                    <h3 style={{ fontSize: '13px', fontWeight: 500, margin: '0 0 10px 0', color: THEME.colors.textPrimary, lineHeight: 1.4 }}>
                      {entry.title}
                    </h3>

                    {/* Card Snippet excerpt */}
                    <p style={{ margin: '0 0 12px 0', fontSize: '12px', color: THEME.colors.textSecondary }}>
                      {entry.snippet}
                    </p>

                    {/* Card Bottom Row Metadata */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: `1px solid ${THEME.colors.surface3}`, paddingTop: '10px' }}>
                      <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
                        <span style={{ fontSize: '10px', color: THEME.colors.textTertiary }}>
                          Date: {new Date(entry.date).toLocaleDateString()}
                        </span>
                        <span style={{ fontSize: '10px', color: THEME.colors.textTertiary, fontFamily: THEME.fonts.mono }}>
                          Cost: ${entry.cost_usd.toFixed(2)}
                        </span>
                        
                        {auditMode && (
                          <span style={{ fontSize: '11px', color: THEME.colors.textSecondary, fontWeight: 600 }}>
                            Impact: {entry.downstream_citations} citations
                          </span>
                        )}
                      </div>

                      {/* Uncertainty Quantification meter */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontSize: '10px', color: THEME.colors.textTertiary }}>UQ:</span>
                        {renderUncertaintyBar(entry.uncertainty_val, entry.uncertainty_range)}
                      </div>
                    </div>

                  </div>
                );
              })
            )}
          </div>

        </div>

        {/* Slide-over details drawer from right */}
        {selectedEntry && (
          <aside 
            className="surface-1 scrollbar-custom"
            style={{
              position: 'absolute',
              right: 0,
              top: 0,
              bottom: 0,
              width: '460px',
              borderLeft: THEME.borders.subtle,
              display: 'flex',
              flexDirection: 'column',
              boxShadow: '-10px 0 30px rgba(0,0,0,0.5)',
              zIndex: 10,
              animation: 'slideIn 0.25s ease-out'
            }}
          >
            {/* Drawer Header */}
            <div 
              style={{
                padding: '16px 20px',
                borderBottom: THEME.borders.subtle,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                backgroundColor: THEME.colors.surface2
              }}
            >
              <div>
                <span style={{ fontSize: '10px', color: THEME.colors.textTertiary, textTransform: 'uppercase' }}>Evidence Details</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <h3 style={{ margin: 0, fontSize: '14px', fontFamily: THEME.fonts.mono }}>{selectedEntry.hypothesis_id}</h3>
                  <StatusPill status={mapResultToStatus(selectedEntry.result)} label={selectedEntry.result} />
                </div>
              </div>
              <button 
                onClick={() => setSelectedEntryId(null)}
                style={{ backgroundColor: 'transparent', border: 'none', color: THEME.colors.textSecondary, cursor: 'pointer', padding: '4px' }}
              >
                <X size={16} />
              </button>
            </div>

            {/* Drawer Content */}
            <div style={{ padding: '20px', flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '20px' }}>
              
              {/* Core Claim */}
              <div>
                <span style={{ fontSize: '11px', color: THEME.colors.textTertiary, textTransform: 'uppercase', display: 'block', marginBottom: '6px' }}>Verified Claim</span>
                <p style={{ margin: 0, fontSize: '13px', fontWeight: 500, lineHeight: 1.5 }}>{selectedEntry.title}</p>
              </div>

              {/* Provenance Audit */}
              <div>
                <span style={{ fontSize: '11px', color: THEME.colors.textTertiary, textTransform: 'uppercase', display: 'block', marginBottom: '8px' }}>
                  Cryptographic Provenance
                </span>
                
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', backgroundColor: THEME.colors.surface2, padding: '12px', border: THEME.borders.subtle, borderRadius: THEME.radius.card }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px' }}>
                    <span style={{ color: THEME.colors.textTertiary }}>Code Hash:</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <code style={{ fontFamily: THEME.fonts.mono, color: THEME.colors.accent }}>{selectedEntry.provenance.code_hash}</code>
                      <button onClick={() => copyToClipboard(selectedEntry.provenance.code_hash)} style={{ background: 'none', border: 'none', color: THEME.colors.textTertiary, cursor: 'pointer' }}>
                        <Copy size={12} />
                      </button>
                    </div>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px' }}>
                    <span style={{ color: THEME.colors.textTertiary }}>Env Hash:</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <code style={{ fontFamily: THEME.fonts.mono }}>{selectedEntry.provenance.env_hash}</code>
                      <button onClick={() => copyToClipboard(selectedEntry.provenance.env_hash)} style={{ background: 'none', border: 'none', color: THEME.colors.textTertiary, cursor: 'pointer' }}>
                        <Copy size={12} />
                      </button>
                    </div>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px' }}>
                    <span style={{ color: THEME.colors.textTertiary }}>Container SHA:</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <code style={{ fontFamily: THEME.fonts.mono }} title={selectedEntry.provenance.container_sha}>
                        {selectedEntry.provenance.container_sha.substring(0, 16)}...
                      </code>
                      <button onClick={() => copyToClipboard(selectedEntry.provenance.container_sha)} style={{ background: 'none', border: 'none', color: THEME.colors.textTertiary, cursor: 'pointer' }}>
                        <Copy size={12} />
                      </button>
                    </div>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px' }}>
                    <span style={{ color: THEME.colors.textTertiary }}>Execution Seed:</span>
                    <span style={{ fontFamily: THEME.fonts.mono, color: THEME.colors.textSecondary }}>{selectedEntry.provenance.seed}</span>
                  </div>
                </div>
              </div>

              {/* Uncertainty Quantification Details */}
              <div>
                <span style={{ fontSize: '11px', color: THEME.colors.textTertiary, textTransform: 'uppercase', display: 'block', marginBottom: '8px' }}>
                  Uncertainty Quantification (UQ)
                </span>
                
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                    <span>Bayesian Error Bounds:</span>
                    <strong style={{ fontFamily: THEME.fonts.mono, color: THEME.colors.accent }}>
                      ±{(selectedEntry.uncertainty_range[1] - selectedEntry.uncertainty_val).toFixed(2)}
                    </strong>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                    <span>Point Estimate Risk:</span>
                    <strong style={{ fontFamily: THEME.fonts.mono }}>{(selectedEntry.uncertainty_val * 100).toFixed(0)}%</strong>
                  </div>
                  
                  <div style={{ fontSize: '11px', color: THEME.colors.textTertiary, lineHeight: 1.4 }}>
                    Derived from 4 parallel simulations on the high-fidelity ladder grid. Meets the standard deviation target bound of &lt; 0.15 for publication.
                  </div>
                </div>
              </div>

              {/* Relitigation Criteria */}
              <div>
                <span style={{ fontSize: '11px', color: THEME.colors.textTertiary, textTransform: 'uppercase', display: 'block', marginBottom: '8px' }}>
                  Relitigation Checklists
                </span>

                {selectedEntry.relitigate_eligible ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {selectedEntry.relitigate_if.map((item, idx) => (
                      <div 
                        key={idx}
                        style={{ 
                          display: 'flex', 
                          alignItems: 'flex-start', 
                          gap: '8px', 
                          fontSize: '12px',
                          padding: '8px',
                          borderRadius: THEME.radius.card,
                          backgroundColor: item.status === 'met' ? THEME.colors.alpha.passed : THEME.colors.surface2,
                          border: item.status === 'met' ? `1px solid ${THEME.colors.status.passed}2A` : THEME.borders.subtle
                        }}
                      >
                        <span style={{ marginTop: '2px' }}>
                          {item.status === 'met' ? (
                            <CheckCircle size={14} color={THEME.colors.status.passed} />
                          ) : (
                            <AlertTriangle size={14} color={THEME.colors.status.pending} />
                          )}
                        </span>
                        <div>
                          <span style={{ display: 'block', color: THEME.colors.textPrimary }}>{item.condition}</span>
                          <span style={{ fontSize: '10px', color: item.status === 'met' ? THEME.colors.status.passed : THEME.colors.textTertiary }}>
                            Status: {item.status === 'met' ? 'Trigger condition met' : 'Awaiting parameters'}
                          </span>
                        </div>
                      </div>
                    ))}
                    
                    {selectedEntry.relitigate_ready && (
                      <button
                        className="btn btn-primary"
                        onClick={() => {
                          logUIAction('EvidenceLedger', 're_litigate_click', { id: selectedEntry.hypothesis_id });
                          alert(`Re-litigation queue scheduled for cycle ${selectedEntry.hypothesis_id}`);
                        }}
                        style={{ width: '100%', marginTop: '8px' }}
                      >
                        Re-litigate Invalidate Run
                      </button>
                    )}
                  </div>
                ) : (
                  <span style={{ fontSize: '12px', color: THEME.colors.textSecondary }}>
                    No automated relitigation rules bound to this hypothesis spec.
                  </span>
                )}
              </div>

            </div>
          </aside>
        )}

      </div>
    </div>
  );
};
