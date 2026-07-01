/** Owner TUI deltas: skin-configurable banner tagline. */

export const DEFAULT_TAGLINE = '⚕ Nous Research · Messenger of the Digital Gods'

export function mergeTaglineFromBranding(
  branding: Record<string, string>,
  fallback: string = DEFAULT_TAGLINE
): string {
  return branding.tagline ?? fallback
}
