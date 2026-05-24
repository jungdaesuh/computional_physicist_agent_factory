/**
 * @file Sparkline.tsx
 * @description SVG-based minimal sparkline chart without gridlines.
 * Designed to show historical trends inline (e.g. daily dollar burn, hypotheses-per-day,
 * and council agreement rate with thresholds) in Mission Control.
 *
 * Use Cases:
 * - Inline telemetry trends in the System Telemetry section of Mission Control.
 * - Miniature metric histories in simulator selectors and budget widgets.
 */

import React, { useState, useRef, useMemo } from 'react';
import { THEME, logUIAction } from './theme';

export interface SparklineProps {
  /** Numerical values to plot in sequence */
  data: number[];
  /** Outer width container property (e.g. '100%', 200) */
  width?: string | number;
  /** Outer height container property (e.g. '40px', 40) */
  height?: string | number;
  /** Primary line color. Defaults to electric cyan. */
  strokeColor?: string;
  /** Thickness of the sparkline path */
  strokeWidth?: number;
  /** Enable translucent area fill below the trendline */
  showArea?: boolean;
  /** Optional horizontal threshold line to draw on the chart */
  threshold?: number;
  /** Color of the threshold line and any points exceeding it */
  thresholdColor?: string;
  /** Enable interactive hover dots and tooltips */
  interactive?: boolean;
  /** Enable smooth Bezier curves instead of straight lines */
  smooth?: boolean;
  /** CSS class suffix */
  className?: string;
}

/**
 * Sparkline renders an SVG path representing a sequence of data points.
 * Features auto-scaling with edge padding, Bezier interpolation, threshold lines,
 * and mouse-hover tooltip tracking.
 */
export const Sparkline: React.FC<SparklineProps> = ({
  data,
  width = '100%',
  height = 40,
  strokeColor = THEME.colors.accent,
  strokeWidth = 1.5,
  showArea = true,
  threshold,
  thresholdColor = THEME.colors.status.pending, // amber for warnings
  interactive = true,
  smooth = true,
  className = '',
}) => {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  // SVG coordinate system limits
  const viewWidth = 100;
  const viewHeight = 40;
  const paddingY = 3;

  // Handle empty or small data arrays gracefully
  const points = useMemo(() => {
    if (!data || data.length < 2) return [];

    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min === 0 ? 1 : max - min;

    return data.map((val, idx) => {
      const x = (idx / (data.length - 1)) * viewWidth;
      // Flip Y axis since SVG 0 is at the top. Add padding to prevent clipping of thick lines.
      const y = viewHeight - paddingY - ((val - min) / range) * (viewHeight - 2 * paddingY);
      return { x, y, value: val };
    });
  }, [data]);

  // Compute SVG path string
  const pathData = useMemo(() => {
    if (points.length < 2) return '';

    let d = `M ${points[0].x} ${points[0].y}`;

    if (smooth) {
      for (let i = 1; i < points.length; i++) {
        const prev = points[i - 1];
        const curr = points[i];
        // Control points placed halfway horizontally between the nodes
        const cpX1 = prev.x + (curr.x - prev.x) / 2;
        const cpY1 = prev.y;
        const cpX2 = prev.x + (curr.x - prev.x) / 2;
        const cpY2 = curr.y;
        d += ` C ${cpX1} ${cpY1}, ${cpX2} ${cpY2}, ${curr.x} ${curr.y}`;
      }
    } else {
      for (let i = 1; i < points.length; i++) {
        d += ` L ${points[i].x} ${points[i].y}`;
      }
    }

    return d;
  }, [points, smooth]);

  // Area fill below the path
  const areaPathData = useMemo(() => {
    if (!pathData || points.length < 2) return '';
    return `${pathData} L ${points[points.length - 1].x} ${viewHeight} L ${points[0].x} ${viewHeight} Z`;
  }, [points, pathData]);

  // Map threshold line to SVG Y coordinate
  const thresholdY = useMemo(() => {
    if (threshold === undefined || data.length === 0) return null;
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min === 0 ? 1 : max - min;
    
    if (threshold < min || threshold > max) return null;
    return viewHeight - paddingY - ((threshold - min) / range) * (viewHeight - 2 * paddingY);
  }, [data, threshold]);

  /**
   * Calculates closest data point on hover based on SVG mouse position.
   */
  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!interactive || !svgRef.current || points.length === 0) return;

    const rect = svgRef.current.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    // Calculate nearest data point index
    const percentX = mouseX / rect.width;
    const index = Math.min(
      points.length - 1,
      Math.max(0, Math.round(percentX * (points.length - 1)))
    );

    if (index !== hoverIndex) {
      setHoverIndex(index);
      logUIAction('Sparkline', 'onHoverChange', { index, val: data[index] });
    }

    setTooltipPos({ x: mouseX, y: mouseY - 25 });
  };

  const handleMouseLeave = () => {
    setHoverIndex(null);
    setTooltipPos(null);
  };

  const gradientId = useMemo(() => `sparkline-grad-${Math.random().toString(36).substr(2, 9)}`, []);

  // Format height/width props to valid CSS sizes
  const parsedWidth = typeof width === 'number' ? `${width}px` : width;
  const parsedHeight = typeof height === 'number' ? `${height}px` : height;

  if (data.length === 0) {
    return (
      <div
        style={{
          width: parsedWidth,
          height: parsedHeight,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: '11px',
          color: THEME.colors.textTertiary,
          fontFamily: THEME.fonts.sans,
          backgroundColor: THEME.colors.surface1,
          borderRadius: THEME.radius.card,
        }}
      >
        No Data
      </div>
    );
  }

  return (
    <div
      className={`sparkline-container ${className}`}
      style={{
        position: 'relative',
        width: parsedWidth,
        height: parsedHeight,
      }}
    >
      <svg
        ref={svgRef}
        viewBox={`0 0 ${viewWidth} ${viewHeight}`}
        width="100%"
        height="100%"
        preserveAspectRatio="none"
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        style={{ display: 'block', overflow: 'visible' }}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={strokeColor} stopOpacity={0.25} />
            <stop offset="100%" stopColor={strokeColor} stopOpacity={0.0} />
          </linearGradient>
        </defs>

        {/* Threshold line */}
        {thresholdY !== null && (
          <line
            x1="0"
            y1={thresholdY}
            x2={viewWidth}
            y2={thresholdY}
            stroke={thresholdColor}
            strokeWidth="0.75"
            strokeDasharray="2,2"
            opacity="0.8"
          />
        )}

        {/* Area fill */}
        {showArea && areaPathData && (
          <path d={areaPathData} fill={`url(#${gradientId})`} />
        )}

        {/* Main trend line */}
        {pathData && (
          <path
            d={pathData}
            fill="none"
            stroke={strokeColor}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}

        {/* Highlight points exceeding threshold */}
        {threshold !== undefined &&
          points.map((p, idx) => {
            if (p.value > threshold) {
              return (
                <circle
                  key={idx}
                  cx={p.x}
                  cy={p.y}
                  r="1.2"
                  fill={thresholdColor}
                />
              );
            }
            return null;
          })}

        {/* Hover elements */}
        {hoverIndex !== null && points[hoverIndex] && (
          <>
            {/* Hover vertical guidelining */}
            <line
              x1={points[hoverIndex].x}
              y1="0"
              x2={points[hoverIndex].x}
              y2={viewHeight}
              stroke="rgba(237, 237, 237, 0.15)"
              strokeWidth="0.75"
            />
            {/* Hover intersection dot */}
            <circle
              cx={points[hoverIndex].x}
              cy={points[hoverIndex].y}
              r="2"
              fill={points[hoverIndex].value > (threshold || Infinity) ? thresholdColor : strokeColor}
              stroke="#0A0A0B"
              strokeWidth="0.75"
            />
          </>
        )}
      </svg>

      {/* Floating Tooltip element */}
      {interactive && hoverIndex !== null && tooltipPos && (
        <div
          style={{
            position: 'absolute',
            left: `${tooltipPos.x}px`,
            top: `${tooltipPos.y}px`,
            transform: 'translateX(-50%)',
            pointerEvents: 'none',
            backgroundColor: THEME.colors.surface3,
            border: THEME.borders.subtle,
            color: THEME.colors.textPrimary,
            fontFamily: THEME.fonts.mono,
            fontSize: '10px',
            fontWeight: 600,
            padding: '2px 6px',
            borderRadius: THEME.radius.pill,
            whiteSpace: 'nowrap',
            boxShadow: '0 2px 4px rgba(0,0,0,0.5)',
            zIndex: 10,
          }}
        >
          {data[hoverIndex].toFixed(2)}
        </div>
      )}
    </div>
  );
};
