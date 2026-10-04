// Tiny external store for high-frequency UI data (hand cursors, metrics) so a
// 30 Hz input stream re-renders only the components that read it.

export type Signal<T> = { get(): T; set(value: T): void; subscribe(listener: () => void): () => void };

export function createSignal<T>(initial: T): Signal<T> {
  let value = initial;
  const listeners = new Set<() => void>();
  return {
    get: () => value,
    set: (next) => {
      value = next;
      for (const listener of listeners) listener();
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
