/**
 * @file LiveLogStream.tsx
 * @description Monospace stream viewer for stdout/stderr logs from running simulations and algorithms.
 * Built with scroll-lock-to-bottom mechanics, dynamic severity coloring, level filtering,
 * and matching-text query highlights.
 *
 * Use Cases:
 * - Streaming terminal logs during generator-verifier loops in the Runner view.
 * - Inspecting historical simulation outputs in the Gate Pipeline View details panel.
 */

import React, { useState, useEffect, useRef, useMemo } from 'react';
import { THEME, logUIAction } from './theme';

export interface LogEntry {
  /** Unique identifier for key mapping */
  id: string;
  /** ISO timestamp or runtime duration tag */
  timestamp: string;
  /** Log severity level */
  level: 'info' | 'warn' | 'error';
  /** Raw console message line */
  message: string;
}

export interface LiveLogStreamProps {
  /** List of log logs. Can be structured objects or raw strings */
  logs: LogEntry[] | string[];
  /** Maximum lines to render to prevent memory leak and performance decay */
  maxLines?: number;
  /** Fixed height or CSS height value of the scrollable log area */
  height?: string | number;
  /** Fired when the operator manually clears the stream buffer */
  onClearLogs?: () => void;
  /** Styling customization */
  className?: string;
}

/**
 * Parses and maps raw terminal output lines to structured LogEntry objects.
 * Identifies standard warning/error prefixes and timestamp formats automatically.
 * @param raw message string
 * @param index unique counter index
 */
function parseRawLogLine(raw: string, index: number): LogEntry {
  const trimmed = raw.trim();
  const lower = trimmed.toLowerCase();
  
  // Rule-based classification of log severity levels
  let level: 'info' | 'warn' | 'error' = 'info';
  if (
    lower.includes('error') ||
    lower.includes('err') ||
    lower.includes('failed') ||
    lower.includes('exception') ||
    lower.includes('nan') ||
    lower.includes('diverged')
  ) {
    level = 'error';
  } else if (lower.includes('warn') || lower.includes('warning') || lower.includes('deprecat')) {
    level = 'warn';
  }

  // Attempt to extract timestamp format matches (e.g. 2026-05-23T16:00:00 or [16:00:00])
  let timestamp = '';
  const timestampRegex = /^\[?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?|\d{2}:\d{2}:\d{2})\]?/;
  const match = trimmed.match(timestampRegex);
  if (match) {
    timestamp = match[1];
  }

  return {
    id: `parsed-log-${index}-${timestamp}`,
    timestamp,
    level,
    message: raw,
  };
}

/**
 * Helper component that renders search terms with a bright highlight background.
 */
const SearchHighlight: React.FC<{ text: string; search: string }> = ({ text, search }) => {
  if (!search) return <>{text}</>;
  
  try {
    // Escape special characters to prevent regex breaking
    const escaped = search.replace(/[-[\]{}()*+?.,\\^$|#\s]/g, '\\$&');
    const parts = text.split(new RegExp(`(${escaped})`, 'gi'));
    
    return (
      <>
        {parts.map((part, i) =>
          part.toLowerCase() === search.toLowerCase() ? (
            <mark
              key={i}
              style={{
                backgroundColor: 'rgba(78, 201, 214, 0.3)',
                color: THEME.colors.textPrimary,
                padding: '0 2px',
                borderRadius: '1px',
              }}
            >
              {part}
            </mark>
          ) : (
            part
          )
        )}
      </>
    );
  } catch (e) {
    return <>{text}</>;
  }
};

/**
 * LiveLogStream renders a high-density, theme-compliant monospace logs feed.
 * Includes scroll lock overrides, keyword filtering, level-based tabs, and file downloads.
 */
export const LiveLogStream: React.FC<LiveLogStreamProps> = ({
  logs,
  maxLines = 1000,
  height = '400px',
  onClearLogs,
  className = '',
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [levelFilter, setLevelFilter] = useState<'all' | 'info' | 'warn' | 'error'>('all');
  const [scrollLocked, setScrollLocked] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);

  // Normalize logs to structured entries and limit output size
  const parsedEntries = useMemo(() => {
    const formatted = logs.map((log, idx) =>
      typeof log === 'string' ? parseRawLogLine(log, idx) : log
    );
    return formatted.slice(-maxLines);
  }, [logs, maxLines]);

  // Apply filters based on level select and search query
  const filteredEntries = useMemo(() => {
    return parsedEntries.filter((entry) => {
      const matchesLevel = levelFilter === 'all' || entry.level === levelFilter;
      const matchesSearch =
        !searchQuery ||
        entry.message.toLowerCase().includes(searchQuery.toLowerCase()) ||
        entry.timestamp.includes(searchQuery);
      return matchesLevel && matchesSearch;
    });
  }, [parsedEntries, levelFilter, searchQuery]);

  // Handle scroll-lock behavior on list updates
  useEffect(() => {
    if (scrollLocked && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [filteredEntries, scrollLocked]);

  /**
   * Monitor user scroll events. If user scrolls up significantly, release lock.
   * If scrolled back to absolute bottom, re-engage scroll lock.
   */
  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;

    const threshold = 35; // margin of error
    const isAtBottom = el.scrollHeight - el.clientHeight - el.scrollTop <= threshold;
    
    if (isAtBottom && !scrollLocked) {
      setScrollLocked(true);
    } else if (!isAtBottom && scrollLocked) {
      setScrollLocked(false);
    }
  };

  /**
   * Generates a plain text file from current filtered entries and downloads it.
   */
  const handleDownload = () => {
    logUIAction('LiveLogStream', 'handleDownload', { totalCount: filteredEntries.length });
    const text = filteredEntries.map((e) => `[${e.timestamp || 'SYSTEM'}] [${e.level.toUpperCase()}] ${e.message}`).join('\n');
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `factory_logs_${new Date().toISOString().replace(/[:.]/g, '_')}.log`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const handleClear = () => {
    logUIAction('LiveLogStream', 'handleClear', {});
    if (onClearLogs) {
      onClearLogs();
    }
  };

  return (
    <div
      className={`live-log-stream ${className}`}
      style={{
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: THEME.colors.background,
        border: THEME.borders.subtle,
        borderRadius: THEME.radius.card,
        overflow: 'hidden',
        color: THEME.colors.textPrimary,
        fontFamily: THEME.fonts.sans,
      }}
    >
      {/* Controls Header */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 12px',
          borderBottom: THEME.borders.subtle,
          backgroundColor: THEME.colors.surface1,
          gap: '8px',
        }}
      >
        {/* Level Filters */}
        <div style={{ display: 'flex', gap: '4px' }}>
          {(['all', 'info', 'warn', 'error'] as const).map((lvl) => {
            const isSelected = levelFilter === lvl;
            return (
              <button
                key={lvl}
                onClick={() => {
                  logUIAction('LiveLogStream', 'setLevelFilter', { level: lvl });
                  setLevelFilter(lvl);
                }}
                style={{
                  backgroundColor: isSelected ? THEME.colors.surface3 : 'transparent',
                  border: isSelected ? `1px solid ${THEME.colors.accent}` : '1px solid transparent',
                  color: isSelected ? THEME.colors.accent : THEME.colors.textSecondary,
                  fontFamily: THEME.fonts.sans,
                  fontSize: '11px',
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  padding: '2px 8px',
                  borderRadius: THEME.radius.pill,
                  cursor: 'pointer',
                  outline: 'none',
                }}
              >
                {lvl}
              </button>
            );
          })}
        </div>

        {/* Action Panel */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {/* Search box */}
          <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke={THEME.colors.textTertiary}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ position: 'absolute', left: '8px' }}
            >
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <input
              type="text"
              placeholder="Filter stdout..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                backgroundColor: THEME.colors.surface2,
                border: THEME.borders.subtle,
                color: THEME.colors.textPrimary,
                fontFamily: THEME.fonts.sans,
                fontSize: '12px',
                padding: '4px 8px 4px 28px',
                borderRadius: THEME.radius.pill,
                width: '150px',
                outline: 'none',
                transition: 'border-color 0.15s ease-in-out',
              }}
              onFocus={(e) => (e.target.style.borderColor = THEME.colors.accent)}
              onBlur={(e) => (e.target.style.borderColor = '#1C1C20')}
            />
          </div>

          {/* Scroll Lock Toggle */}
          <button
            onClick={() => {
              logUIAction('LiveLogStream', 'setScrollLocked', { nextState: !scrollLocked });
              setScrollLocked(!scrollLocked);
            }}
            title={scrollLocked ? "Unlock autoscroll" : "Lock to bottom"}
            style={{
              backgroundColor: 'transparent',
              border: THEME.borders.subtle,
              color: scrollLocked ? THEME.colors.accent : THEME.colors.textSecondary,
              padding: '4px 6px',
              borderRadius: THEME.radius.pill,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              {scrollLocked ? (
                <>
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                  <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                </>
              ) : (
                <>
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                  <path d="M7 11V7a5 5 0 0 1 9.9-1"></path>
                </>
              )}
            </svg>
            <span style={{ fontSize: '10px', marginLeft: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
              {scrollLocked ? "Locked" : "Free"}
            </span>
          </button>

          {/* Download Logs */}
          <button
            onClick={handleDownload}
            title="Download log file"
            style={{
              backgroundColor: 'transparent',
              border: THEME.borders.subtle,
              color: THEME.colors.textSecondary,
              padding: '4px',
              borderRadius: THEME.radius.pill,
              cursor: 'pointer',
              display: 'flex',
            }}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
          </button>

          {/* Clear Logs */}
          {onClearLogs && (
            <button
              onClick={handleClear}
              title="Clear terminal buffer"
              style={{
                backgroundColor: 'transparent',
                border: THEME.borders.subtle,
                color: THEME.colors.textSecondary,
                padding: '4px',
                borderRadius: THEME.radius.pill,
                cursor: 'pointer',
                display: 'flex',
              }}
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Log list area */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        style={{
          height: height,
          overflowY: 'auto',
          padding: '12px',
          margin: 0,
          backgroundColor: '#070708', // pure dark container backing
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
        }}
      >
        {filteredEntries.length === 0 ? (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              color: THEME.colors.textTertiary,
              fontSize: '12px',
              fontStyle: 'italic',
            }}
          >
            No logs in buffer matching criteria.
          </div>
        ) : (
          filteredEntries.map((entry) => {
            // Apply level coloring
            let levelColor: string = THEME.colors.textSecondary;
            if (entry.level === 'error') {
              levelColor = THEME.colors.status.failed;
            } else if (entry.level === 'warn') {
              levelColor = THEME.colors.status.pending;
            }

            return (
              <div
                key={entry.id}
                style={{
                  display: 'flex',
                  fontFamily: THEME.fonts.mono,
                  fontSize: '12px',
                  lineHeight: '1.5',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                }}
              >
                {/* Timestamp tag (grayed out) */}
                {entry.timestamp && (
                  <span
                    style={{
                      color: THEME.colors.textTertiary,
                      marginRight: '8px',
                      userSelect: 'none',
                    }}
                  >
                    [{entry.timestamp}]
                  </span>
                )}
                {/* Message line with match highlights */}
                <span style={{ color: levelColor }}>
                  <SearchHighlight text={entry.message} search={searchQuery} />
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
