/**
 * @file theme.ts
 * @description Centralized design tokens and theme configuration for the AI Co-Computational Physicist Factory UI.
 * Establishes consistent palettes, typography, spacing, and styling invariants to ensure alignment
 * with the operations console aesthetic (Linear/Datadog hybrid dark mode).
 *
 * Use Cases:
 * - Direct style applications for components using inline styles or CSS modules.
 * - Uniform status color lookups based on pipeline states.
 * - Reusable Tailwind-like constants if a bundler setup maps style classes.
 */

// Global theme definition representing the design system variables
export const THEME = {
  colors: {
    // Operations console near-black background
    background: '#0A0A0B',
    // Elevation surfaces for container depth
    surface1: '#111114',
    surface2: '#161619',
    surface3: '#1C1C20',
    // Text opacity steps for strong typographic hierarchy
    textPrimary: '#EDEDED',
    textSecondary: 'rgba(237, 237, 237, 0.60)',
    textTertiary: 'rgba(237, 237, 237, 0.40)',
    // Cyan accent for keyboard navigation focus, primary controls, and active states
    accent: '#4EC9D6',
    // Status colors reserved specifically for system execution state, not decoration
    status: {
      passed: '#3DDC97',
      failed: '#FF5C5C',
      pending: '#FFB84D',
      running: '#5B9BD5',
      dissent: '#A78BFA',
      parked: '#A78BFA',
      qualified: '#FFB84D', // Amber with border
    },
    // Truncated transparent overlays for hover effects and backgrounds
    alpha: {
      passed: 'rgba(61, 220, 151, 0.08)',
      failed: 'rgba(255, 92, 92, 0.08)',
      pending: 'rgba(255, 184, 77, 0.08)',
      running: 'rgba(91, 155, 213, 0.08)',
      dissent: 'rgba(167, 139, 250, 0.08)',
      parked: 'rgba(167, 139, 250, 0.08)',
      qualified: 'rgba(255, 184, 77, 0.04)',
      accent: 'rgba(78, 201, 214, 0.08)',
    }
  },
  fonts: {
    // Inter for sans-serif UI components
    sans: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    // JetBrains Mono for metrics, telemetry, and code blocks
    mono: '"JetBrains Mono", Menlo, Monaco, Consolas, "Fira Code", monospace',
  },
  radius: {
    pill: '2px', // Status pills have strict 2px radius
    card: '4px', // Max corner radius for containers, controls, and elements
  },
  borders: {
    subtle: '1px solid #1C1C20',
    active: '1px solid #4EC9D6',
  }
} as const;

/**
 * Logs a component function call with its parameters to preserve the audit trail of UI interactions.
 * Helps with debuggability of asynchronous actions and view switches.
 * @param componentName The name of the React component making the call.
 * @param functionName The name of the function or event being triggered.
 * @param params Arbitrary payload representing arguments passed to the function.
 */
export function logUIAction(componentName: string, functionName: string, params: Record<string, unknown>): void {
  console.info(
    `[UI-INFO] Component: ${componentName} | Function: ${functionName} | Params:`,
    JSON.stringify(params, (_, val) => (typeof val === 'function' ? 'Function' : val), 2)
  );
}
