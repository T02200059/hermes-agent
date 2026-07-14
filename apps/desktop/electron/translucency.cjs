/**
 * Pure helper for window translucency. The main process maps the 0–100
 * lever to the native window opacity (`setOpacity`); this is the one place
 * that conversion happens, kept pure so it's unit-testable without booting
 * Electron.
 *
 * The floor differs per platform. Windows has no vibrancy/backdrop to soften
 * `setOpacity` (it's flat whole-window alpha over an opaque surface, so each
 * percent reads far harsher than macOS's frosted vibrancy). A shallower Windows
 * floor keeps the grades as subtle as they are on macOS — without it 5% already
 * looks nearly half-transparent on Windows. 0 → fully opaque on both.
 */

const MACOS_OPACITY_FLOOR = 0.3
const WINDOWS_OPACITY_FLOOR = 0.75

function opacityForIntensity(intensity, isWindows) {
  const floor = isWindows ? WINDOWS_OPACITY_FLOOR : MACOS_OPACITY_FLOOR
  const n = Number.isFinite(intensity) ? Math.min(100, Math.max(0, intensity)) : 0
  return 1 - (n / 100) * (1 - floor)
}

module.exports = {
  MACOS_OPACITY_FLOOR,
  WINDOWS_OPACITY_FLOOR,
  opacityForIntensity
}
