/** Owner TUI deltas: skin-configurable status bar colors. */

export interface StatusBarColors {
  statusBg: string
  statusFg: string
}

export function mergeStatusBarFromSkin(
  colors: Record<string, string>,
  fallback: StatusBarColors
): StatusBarColors {
  return {
    statusBg: colors.status_bar_bg ?? fallback.statusBg,
    statusFg: colors.status_bar_text ?? fallback.statusFg
  }
}
