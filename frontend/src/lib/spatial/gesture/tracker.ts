// Hand identity tracking across frames.
//
// Providers report hands per frame with an unstable order and a handedness
// label that can flip (especially when hands cross or turn). The tracker gives
// each physical hand a stable track id by spatial association, smooths its
// landmarks, keeps it alive ("coasting") through brief occlusion, rejects
// teleport jumps as new detections, and stabilises handedness by voting.

import type { GestureConfig } from "./config.ts";
import { PointSetFilter } from "./filters.ts";
import { computeFeatures, palmCenter, type HandFeatures, type HandFrame, type HandObservation, type Handedness, type ImageToViewport } from "./hand.ts";

export type TrackState = "tracking" | "coasting";

export type TrackedHand = {
  id: number;
  handedness: Handedness;
  /** |vote| in [0, 1]: how consistently the provider labelled this hand. */
  handednessConfidence: number;
  state: TrackState;
  /** Provider score of the latest observation (0 while coasting). */
  score: number;
  degraded: boolean;
  firstSeen: number;
  lastSeen: number;
  /** Cumulative count of single-frame outliers rejected for this hand. */
  glitches: number;
  observation: HandObservation;
  features: HandFeatures;
};

type Track = TrackedHand & {
  vote: number; image: PointSetFilter; world: PointSetFilter; rawPalm: { x: number; y: number };
  pending: { x: number; y: number } | null;
};

export type TrackerEvents = { acquired: number[]; lost: number[] };

export class HandTracker {
  private tracks: Track[] = [];
  private nextId = 1;
  lastEvents: TrackerEvents = { acquired: [], lost: [] };

  constructor(private readonly config: GestureConfig, private readonly swapHandedness: () => boolean = () => false) {}

  reset(): void {
    this.tracks = [];
    this.lastEvents = { acquired: [], lost: [] };
  }

  update(frame: HandFrame, toViewport: ImageToViewport): TrackedHand[] {
    const now = frame.timestamp;
    const aspect = frame.width > 0 && frame.height > 0 ? frame.width / frame.height : 16 / 9;
    const observations = frame.hands.slice(0, this.config.maxHands).map((hand) => ({
      hand: this.swapHandedness() ? { ...hand, handedness: (hand.handedness === "Left" ? "Right" : "Left") as Handedness } : hand,
      palm: palmCenter(hand.landmarks),
    }));
    // Greedy association on viewport-independent image palm distance, with a
    // small penalty when the provider's label disagrees with the track's vote.
    const pairs: Array<{ track: Track; index: number; cost: number }> = [];
    for (const track of this.tracks) {
      observations.forEach((observation, index) => {
        const distance = Math.hypot((observation.palm.x - track.rawPalm.x) * aspect, observation.palm.y - track.rawPalm.y);
        if (distance > this.config.matchDistance) return;
        const label = observation.hand.handedness === "Right" ? 1 : -1;
        const disagreement = Math.sign(track.vote) !== 0 && Math.sign(track.vote) !== label ? 0.04 : 0;
        pairs.push({ track, index, cost: distance + disagreement });
      });
    }
    pairs.sort((a, b) => a.cost - b.cost);
    const usedTracks = new Set<number>();
    const usedObservations = new Set<number>();
    const events: TrackerEvents = { acquired: [], lost: [] };
    for (const pair of pairs) {
      if (usedTracks.has(pair.track.id) || usedObservations.has(pair.index)) continue;
      usedTracks.add(pair.track.id);
      usedObservations.add(pair.index);
      this.observe(pair.track, observations[pair.index].hand, observations[pair.index].palm, now, aspect, toViewport);
    }
    for (const track of this.tracks) {
      if (usedTracks.has(track.id)) continue;
      track.state = "coasting";
      track.score = 0;
    }
    const survivors: Track[] = [];
    for (const track of this.tracks) {
      if (track.state === "coasting" && now - track.lastSeen > this.config.graceMs) events.lost.push(track.id);
      else survivors.push(track);
    }
    this.tracks = survivors;
    observations.forEach((observation, index) => {
      if (usedObservations.has(index) || this.tracks.length >= this.config.maxHands) return;
      const track = this.create(observation.hand, observation.palm, now, aspect, toViewport);
      this.tracks.push(track);
      events.acquired.push(track.id);
    });
    this.lastEvents = events;
    return this.tracks.map((track) => this.publicTrack(track)).sort((a, b) => a.id - b.id);
  }

  private create(hand: HandObservation, palm: { x: number; y: number }, now: number, aspect: number, toViewport: ImageToViewport): Track {
    const track = {
      id: this.nextId++,
      vote: 0,
      image: new PointSetFilter(21, this.config.imageFilter),
      world: new PointSetFilter(21, this.config.worldFilter),
      rawPalm: palm,
      pending: null,
      glitches: 0,
      firstSeen: now,
    } as Track;
    this.observe(track, hand, palm, now, aspect, toViewport);
    return track;
  }

  private observe(track: Track, hand: HandObservation, palm: { x: number; y: number }, now: number, aspect: number, toViewport: ImageToViewport): void {
    if (track.observation) {
      const jump = Math.hypot((palm.x - track.rawPalm.x) * aspect, palm.y - track.rawPalm.y);
      if (track.pending) {
        const confirms = Math.hypot((palm.x - track.pending.x) * aspect, palm.y - track.pending.y) < this.config.outlierJump / 2;
        track.pending = null;
        if (!confirms && jump >= this.config.outlierJump) {
          // Neither back on the old path nor confirming the new one: hold again.
          track.pending = palm;
          track.lastSeen = now;
          track.state = "tracking";
          return;
        }
        if (!confirms) track.glitches += 1; // returned to the old path: the jump was a glitch
      } else if (jump >= this.config.outlierJump) {
        // Hold the previous smoothed pose for one frame; accept only if confirmed.
        track.pending = palm;
        track.lastSeen = now;
        track.state = "tracking";
        return;
      }
    }
    const label = hand.handedness === "Right" ? 1 : -1;
    const weight = Math.min(Math.max(hand.handednessScore, 0), 1);
    track.vote = Math.max(-1, Math.min(1, track.vote * 0.85 + label * weight * 0.15 * (track.vote === 0 ? 6.67 : 1)));
    const smoothed: HandObservation = {
      handedness: track.vote >= 0 ? "Right" : "Left",
      handednessScore: hand.handednessScore,
      landmarks: track.image.filter(hand.landmarks, now),
      worldLandmarks: hand.worldLandmarks ? track.world.filter(hand.worldLandmarks, now) : undefined,
    };
    track.rawPalm = palm;
    track.observation = smoothed;
    track.features = computeFeatures(smoothed, aspect, toViewport);
    track.handedness = smoothed.handedness;
    track.handednessConfidence = Math.abs(track.vote);
    track.state = "tracking";
    track.score = hand.handednessScore;
    track.degraded = hand.handednessScore < this.config.minScore;
    track.lastSeen = now;
  }

  private publicTrack(track: Track): TrackedHand {
    return {
      id: track.id, handedness: track.handedness, handednessConfidence: track.handednessConfidence,
      state: track.state, score: track.score, degraded: track.degraded, firstSeen: track.firstSeen,
      lastSeen: track.lastSeen, glitches: track.glitches, observation: track.observation, features: track.features,
    };
  }
}
