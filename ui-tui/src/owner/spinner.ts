/** Owner TUI deltas: skin-configurable spinner faces and thinking verbs. */

export interface ThemeSpinner {
  waitingFaces: string[]
  thinkingVerbs: string[]
}

export const DEFAULT_SPINNER: ThemeSpinner = {
  waitingFaces:
    '(｡•́︿•̀｡) (◔_◔) (¬‿¬) ( •_•)>⌐■-■ (⌐■_■) (´･_･`) ◉_◉ (°ロ°) ( ˘⌣˘)♡ ヽ(>∀<☆)☆ ٩(๑❛ᴗ❛๑)۶ (⊙_⊙) (¬_¬) ( ͡° ͜ʖ ͡°) ಠ_ಠ'.split(
      ' '
    ),
  thinkingVerbs:
    'pondering contemplating musing cogitating ruminating deliberating mulling reflecting processing reasoning analyzing computing synthesizing formulating brainstorming'.split(
      ' '
    )
}

export function mergeSpinnerFromSkin(
  spinner: Record<string, string[]> | undefined,
  fallback: ThemeSpinner = DEFAULT_SPINNER
): ThemeSpinner {
  return {
    waitingFaces: spinner?.waiting_faces ?? fallback.waitingFaces,
    thinkingVerbs: spinner?.thinking_verbs ?? fallback.thinkingVerbs
  }
}