import type { ProductMood } from "./platform";

/**
 * CALM / BEST OF BEST / HARDCARRY are anchor points on one continuous 0..1
 * energy spectrum, not three unrelated themes. Every HUD visual (character
 * lighting, halo, HUD line luminance, module borders, particles, waveform)
 * derives from this single number via CSS calc()/clamp(), so moving between
 * anchors ramps through intermediate values instead of swapping assets.
 */
export const ENERGY_ANCHORS: Record<ProductMood, number> = {
  calm: 0.08,
  best: 0.5,
  hardcarry: 1,
};

export type EnergySignal = {
  /** A voice session is actively listening, thinking, speaking, or interrupted. */
  voiceActive: boolean;
  /** A request is in flight (chat, generation, research). */
  busy: boolean;
  /** A heavier operation is running (full voice session, active task execution). */
  intensive: boolean;
};

/**
 * Blends the selected mood anchor with small live-activity offsets so the
 * spectrum responds to what AKASHI is actually doing, rather than jumping
 * between exactly three fixed values.
 */
export function computeEnergy(mood: ProductMood, signal: EnergySignal): number {
  let energy = ENERGY_ANCHORS[mood];
  if (signal.voiceActive) energy += 0.05;
  if (signal.busy) energy += 0.04;
  if (signal.intensive) energy += 0.03;
  return Math.min(1, Math.max(0, energy));
}
