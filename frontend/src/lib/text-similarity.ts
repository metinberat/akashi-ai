// Lightweight, dependency-free text comparison used to tell AKASHI's own TTS bleeding into the
// microphone apart from a real user interruption during desktop barge-in. Nothing here persists
// input beyond the call — callers pass transient in-memory strings only.

export function normalizeForCompare(text: string): string {
  return text
    .toLocaleLowerCase("tr-TR")
    .normalize("NFKC")
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .replace(/\s+/gu, " ")
    .trim();
}

export function tokenize(text: string): string[] {
  const normalized = normalizeForCompare(text);
  return normalized ? normalized.split(" ") : [];
}

export function diceCoefficient(a: string[], b: string[]): number {
  if (a.length === 0 || b.length === 0) return 0;
  const setA = new Set(a);
  const setB = new Set(b);
  let overlap = 0;
  for (const token of setA) if (setB.has(token)) overlap += 1;
  return (2 * overlap) / (setA.size + setB.size);
}

// Longest-common-subsequence ratio over normalized character strings, capped for safety since
// these strings are always short (a few seconds of speech at most).
export function sequenceSimilarity(a: string, b: string): number {
  const m = Math.min(a.length, 400);
  const n = Math.min(b.length, 400);
  if (m === 0 || n === 0) return 0;
  const row = new Array<number>(n + 1).fill(0);
  for (let i = 1; i <= m; i += 1) {
    let previousDiagonal = 0;
    for (let j = 1; j <= n; j += 1) {
      const temp = row[j];
      row[j] = a[i - 1] === b[j - 1] ? previousDiagonal + 1 : Math.max(row[j], row[j - 1]);
      previousDiagonal = temp;
    }
  }
  return (2 * row[n]) / (m + n);
}

export function similarityScore(candidate: string, reference: string): number {
  const tokenScore = diceCoefficient(tokenize(candidate), tokenize(reference));
  const sequenceScore = sequenceSimilarity(normalizeForCompare(candidate), normalizeForCompare(reference));
  return Math.max(tokenScore, sequenceScore);
}

// The short window of the TTS excerpt that's actually audible right now, derived from the
// SpeechSynthesisUtterance boundary event's charIndex plus a small buffer on either side.
export function extractSpokenWindow(excerpt: string, charIndex: number, radius = 70): string {
  if (!excerpt) return "";
  const start = Math.max(0, charIndex - radius);
  const end = Math.min(excerpt.length, charIndex + radius);
  return excerpt.slice(start, end);
}

const HEADSET_PATTERN = /headset|headphone|earbud|earphone|airpods|buds\b|kulakl[ıi]k|arctis|steelseries|hyperx|razer\s*(kraken|barracuda)|corsair\s*(hs|void)|logitech\s*g\s*(pro|433|533|633|733)|wh-1000|wf-1000|beats|jabra/iu;

export function isLikelyHeadsetDevice(label: string | null | undefined): boolean {
  return HEADSET_PATTERN.test(label || "");
}

/**
 * Decide whether a barge-in candidate transcript is probable speaker bleed (AKASHI hearing
 * itself) rather than a real human interruption.
 *
 * Compares primarily against the currently-audible window of the TTS excerpt; falls back to the
 * full excerpt only when the window is too short to be conclusive (e.g. right at the start of
 * playback, or the browser didn't fire boundary events).
 */
export function isProbableEcho(
  candidate: string,
  spokenWindow: string,
  fullExcerpt: string,
  echoThreshold: number,
): boolean {
  const trimmedCandidate = candidate.trim();
  if (!trimmedCandidate) return false;
  if (spokenWindow && tokenize(spokenWindow).length >= 2) {
    return similarityScore(trimmedCandidate, spokenWindow) >= echoThreshold;
  }
  if (!fullExcerpt) return false;
  return similarityScore(trimmedCandidate, fullExcerpt) >= echoThreshold + 0.05;
}
