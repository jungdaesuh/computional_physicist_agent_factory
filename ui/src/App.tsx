/**
 * @file App.tsx
 * @description The main shell component for the AI Co-Computational Physicist Factory UI.
 * Implements a premium sidebar layout, dark-mode visual structure, and routing for all
 * dashboard views. Supports a collapsed sidebar state and copyable provenance hashes.
 *
 * Use Cases:
 * 1. Global navigation between operations dashboards (Mission Control, Catalog Browser, Evidence Ledger, Settings).
 * 2. Parameter parsing for dynamic reports and deliberation sessions via React Router wrapper routes.
 * 3. Consistent layout shell adhering to operator console design tokens (near-black, electric cyan, 4px corners).
 * 4. Verification of system state through visible and copyable environment/source cryptographic hashes.
 */

import React, { useEffect, useState } from 'react';
import { Routes, Route, Link, useLocation, useParams } from 'react-router-dom';
import { 
  LayoutDashboard, 
  Settings as SettingsIcon, 
  Cpu,
  Database,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Copy,
  Check
} from 'lucide-react';

import { THEME, logUIAction } from './components/theme';
import { MissionControl } from './views/MissionControl';
import { DeliberationView } from './views/DeliberationView';
import { RunReportReader } from './views/RunReportReader';
import { Settings } from './views/Settings';
import { CatalogBrowser } from './views/CatalogBrowser';
import { EvidenceLedger } from './views/EvidenceLedger';
import { ComponentShowcase } from './components/ComponentShowcase';

/**
 * Route wrapper for DeliberationView to extract sessionId parameter.
 * @returns React.JSX.Element
 */
const DeliberationRouteWrapper: React.FC = () => {
  const { sessionId } = useParams<{ sessionId: string }>();
  return <DeliberationView sessionId={sessionId || 'mock-session-123'} />;
};

/**
 * Route wrapper for RunReportReader to extract reportId parameter.
 * @returns React.JSX.Element
 */
const ReportRouteWrapper: React.FC = () => {
  const { reportId } = useParams<{ reportId: string }>();
  return <RunReportReader reportId={reportId || '0000000000000000000000000000000000000000000000000000000000000000'} />;
};

/**
 * The Root App Component with Sidebar Layout.
 * @returns React.JSX.Element
 */
export default function App(): React.JSX.Element {
  const location = useLocation();
  const [isCollapsed, setIsCollapsed] = useState<boolean>(false);
  const [copiedField, setCopiedField] = useState<string | null>(null);

  // Mock provenance hashes for the running system
  const provenance = {
    gitCommit: 'a1b2c3d4e5f6',
    containerSha: 'sha256:8f2d1e0c3b9a...'
  };

  useEffect(() => {
    logUIAction('App', 'mount', { path: location.pathname });
  }, [location]);

  /**
   * Toggles the sidebar expanded/collapsed state and logs the action.
   */
  const handleToggleSidebar = () => {
    logUIAction('App', 'toggle_sidebar', { previousState: isCollapsed, nextState: !isCollapsed });
    setIsCollapsed(!isCollapsed);
  };

  /**
   * Copies the given provenance hash to the clipboard and shows a temporary success state.
   * @param key The key identifier for the copied field
   * @param text The text to copy to clipboard
   */
  const copyProvenanceHash = (key: string, text: string) => {
    logUIAction('App', 'copy_provenance_hash', { field: key, value: text });
    navigator.clipboard.writeText(text);
    setCopiedField(key);
    setTimeout(() => setCopiedField(null), 1500);
  };

  // Main navigation items
  const navItems = [
    { path: '/', label: 'Mission Control', icon: LayoutDashboard },
    { path: '/catalog', label: 'Catalog Browser', icon: Database },
    { path: '/ledger', label: 'Evidence Ledger', icon: BookOpen },
    { path: '/settings', label: 'Settings', icon: SettingsIcon },
  ];

  return (
    <div style={{ display: 'flex', minHeight: '100vh', backgroundColor: THEME.colors.background, fontFamily: THEME.fonts.sans }}>
      {/* Sidebar Navigation */}
      <aside 
        style={{
          width: isCollapsed ? '64px' : '240px',
          backgroundColor: THEME.colors.surface1,
          borderRight: THEME.borders.subtle,
          display: 'flex',
          flexDirection: 'column',
          flexShrink: 0,
          transition: 'width 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
          position: 'relative'
        }}
      >
        {/* Brand / Logo */}
        <div 
          style={{
            padding: isCollapsed ? '24px 0' : '24px 20px',
            borderBottom: THEME.borders.subtle,
            display: 'flex',
            alignItems: 'center',
            justifyContent: isCollapsed ? 'center' : 'space-between',
            gap: '10px'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Cpu size={20} color={THEME.colors.accent} />
            {!isCollapsed && (
              <div>
                <span style={{ fontWeight: 600, color: THEME.colors.textPrimary, fontSize: '14px', letterSpacing: '-0.02em', display: 'block' }}>
                  StellaEvolve
                </span>
                <span style={{ fontSize: '10px', color: THEME.colors.textTertiary, fontFamily: THEME.fonts.mono }}>
                  v0.1.0-alpha
                </span>
              </div>
            )}
          </div>

          {/* Expanded Toggle Button */}
          {!isCollapsed && (
            <button 
              onClick={handleToggleSidebar}
              style={{
                background: 'none',
                border: 'none',
                color: THEME.colors.textTertiary,
                cursor: 'pointer',
                padding: '4px',
                display: 'flex',
                alignItems: 'center',
                borderRadius: '2px',
                transition: 'color 0.15s ease'
              }}
              title="Collapse Sidebar"
            >
              <ChevronLeft size={16} />
            </button>
          )}
        </div>

        {/* Collapsed Toggle Button (Overlaid on border when collapsed) */}
        {isCollapsed && (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '8px 0' }}>
            <button 
              onClick={handleToggleSidebar}
              style={{
                background: 'none',
                border: THEME.borders.subtle,
                color: THEME.colors.textTertiary,
                cursor: 'pointer',
                padding: '6px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                borderRadius: THEME.radius.card,
                backgroundColor: THEME.colors.surface2
              }}
              title="Expand Sidebar"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        )}

        {/* Nav Links */}
        <nav style={{ flex: 1, padding: '16px 12px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = location.pathname === item.path;

            return (
              <Link
                key={item.path}
                to={item.path}
                onClick={() => logUIAction('App', 'navigation_click', { path: item.path })}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: isCollapsed ? 'center' : 'flex-start',
                  gap: isCollapsed ? '0' : '10px',
                  padding: '8px 12px',
                  borderRadius: THEME.radius.card,
                  color: isActive ? THEME.colors.accent : THEME.colors.textSecondary,
                  backgroundColor: isActive ? THEME.colors.alpha.accent : 'transparent',
                  textDecoration: 'none',
                  fontSize: '13px',
                  fontWeight: isActive ? 500 : 400,
                  border: isActive ? THEME.borders.active : '1px solid transparent',
                  transition: 'all 0.15s ease',
                }}
                title={isCollapsed ? item.label : undefined}
              >
                <Icon size={16} color={isActive ? THEME.colors.accent : THEME.colors.textSecondary} />
                {!isCollapsed && <span>{item.label}</span>}
              </Link>
            );
          })}
        </nav>

        {/* Copyable Provenance Hashes and Daemon Info */}
        <div 
          style={{ 
            padding: isCollapsed ? '16px 8px' : '16px 20px', 
            borderTop: THEME.borders.subtle, 
            fontSize: '11px', 
            color: THEME.colors.textTertiary, 
            fontFamily: THEME.fonts.mono,
            display: 'flex',
            flexDirection: 'column',
            gap: '8px'
          }}
        >
          {isCollapsed ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
              <button
                onClick={() => copyProvenanceHash('git', provenance.gitCommit)}
                style={{ background: 'none', border: 'none', color: THEME.colors.textTertiary, cursor: 'pointer', padding: '2px' }}
                title="Copy Commit Hash"
              >
                {copiedField === 'git' ? <Check size={12} color={THEME.colors.status.passed} /> : <Copy size={12} />}
              </button>
            </div>
          ) : (
            <>
              {/* Copyable Commit Hash */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>commit:</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <span style={{ color: THEME.colors.textSecondary }}>{provenance.gitCommit.substring(0, 7)}</span>
                  <button
                    onClick={() => copyProvenanceHash('git', provenance.gitCommit)}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: THEME.colors.textTertiary,
                      cursor: 'pointer',
                      padding: '2px',
                      display: 'flex',
                      alignItems: 'center'
                    }}
                    title="Copy Git Commit Hash"
                  >
                    {copiedField === 'git' ? <Check size={10} color={THEME.colors.status.passed} /> : <Copy size={10} />}
                  </button>
                </div>
              </div>

              {/* Copyable Container SHA */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>container:</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <span style={{ color: THEME.colors.textSecondary }}>{provenance.containerSha.substring(7, 14)}</span>
                  <button
                    onClick={() => copyProvenanceHash('container', provenance.containerSha)}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: THEME.colors.textTertiary,
                      cursor: 'pointer',
                      padding: '2px',
                      display: 'flex',
                      alignItems: 'center'
                    }}
                    title="Copy Container SHA"
                  >
                    {copiedField === 'container' ? <Check size={10} color={THEME.colors.status.passed} /> : <Copy size={10} />}
                  </button>
                </div>
              </div>

              <div style={{ borderTop: `1px solid ${THEME.colors.surface3}`, paddingTop: '8px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <div>daemon: running</div>
                <div>mhd: healthy</div>
              </div>
            </>
          )}
        </div>
      </aside>

      {/* Main Content Area */}
      <main style={{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
        <Routes>
          <Route path="/" element={<MissionControl />} />
          <Route path="/catalog" element={<CatalogBrowser />} />
          <Route path="/ledger" element={<EvidenceLedger />} />
          <Route path="/deliberation" element={<DeliberationRouteWrapper />} />
          <Route path="/deliberation/:sessionId" element={<DeliberationRouteWrapper />} />
          <Route path="/report" element={<ReportRouteWrapper />} />
          <Route path="/report/:reportId" element={<ReportRouteWrapper />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/showcase" element={<ComponentShowcase />} />
        </Routes>
      </main>
    </div>
  );
}
