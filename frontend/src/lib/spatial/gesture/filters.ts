// One Euro filter (Casiez, Roussel, Vogel 2012): adaptive low-pass filtering.
// Slow motion → low cutoff (removes landmark jitter); fast motion → high cutoff
// (keeps latency low). Parameters are per-signal and documented as tunables.

export type OneEuroParams = { minCutoff: number; beta: number; dCutoff: number };

function alpha(cutoff: number, dtSeconds: number): number {
  const tau = 1 / (2 * Math.PI * cutoff);
  return 1 / (1 + tau / dtSeconds);
}

export class OneEuroFilter {
  private value: number | null = null;
  private derivative = 0;
  private time: number | null = null;

  constructor(private readonly params: OneEuroParams) {}

  filter(value: number, timestampMs: number): number {
    if (this.value === null || this.time === null) {
      this.value = value;
      this.time = timestampMs;
      return value;
    }
    if (timestampMs <= this.time) return this.value;
    const dt = Math.min((timestampMs - this.time) / 1000, 0.5);
    this.time = timestampMs;
    const rawDerivative = (value - this.value) / dt;
    this.derivative += alpha(this.params.dCutoff, dt) * (rawDerivative - this.derivative);
    const cutoff = this.params.minCutoff + this.params.beta * Math.abs(this.derivative);
    this.value += alpha(cutoff, dt) * (value - this.value);
    return this.value;
  }

  reset(): void {
    this.value = null;
    this.time = null;
    this.derivative = 0;
  }
}

/** Filters a fixed-size list of 3D points (e.g. 21 landmarks) independently per axis. */
export class PointSetFilter {
  private readonly filters: OneEuroFilter[];

  constructor(count: number, params: OneEuroParams) {
    this.filters = Array.from({ length: count * 3 }, () => new OneEuroFilter(params));
  }

  filter(points: Array<{ x: number; y: number; z: number }>, timestampMs: number) {
    return points.map((p, i) => ({
      x: this.filters[i * 3].filter(p.x, timestampMs),
      y: this.filters[i * 3 + 1].filter(p.y, timestampMs),
      z: this.filters[i * 3 + 2].filter(p.z ?? 0, timestampMs),
    }));
  }

  reset(): void {
    for (const filter of this.filters) filter.reset();
  }
}
