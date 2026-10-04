// Remote voice input: speech → text on the device, then a transcript to Core.
// Audio is never sent to AKASHI Core by this client.
//
// Engines, in order of preference:
// * native     — the Capacitor app's platform speech recognition (iOS/Android).
// * web-speech — the browser Speech API. Some browsers (e.g. Chrome) send audio to
//                their vendor's cloud service; the UI labels this engine so.
// Typed text is always available; voice is optional and never required.

import { Capacitor } from "@capacitor/core";

export type VoiceEngine = "native" | "web-speech" | "none";

type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  continuous: boolean;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string; confidence: number }>> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  abort(): void;
};

function webSpeech(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === "undefined") return null;
  const candidate = (window as unknown as { SpeechRecognition?: unknown; webkitSpeechRecognition?: unknown });
  return (candidate.SpeechRecognition ?? candidate.webkitSpeechRecognition ?? null) as (new () => SpeechRecognitionLike) | null;
}

export function availableEngine(): VoiceEngine {
  if (Capacitor.isNativePlatform()) return "native";
  return webSpeech() ? "web-speech" : "none";
}

export const ENGINE_NOTES: Record<VoiceEngine, string> = {
  native: "On-device platform speech recognition",
  "web-speech": "Browser speech recognition (may use the browser vendor's cloud service)",
  none: "Voice input is not available here; type instead",
};

export type Transcript = { text: string; confidence: number | null; engine: VoiceEngine };

let active: SpeechRecognitionLike | null = null;

export async function listenOnce(language: "auto" | "tr" | "en" = "auto"): Promise<Transcript> {
  const engine = availableEngine();
  if (engine === "native") {
    const { recognizeOnce } = await import("../voice");
    return { text: await recognizeOnce(language), confidence: null, engine };
  }
  const Recognition = webSpeech();
  if (!Recognition) throw new Error(ENGINE_NOTES.none);
  return new Promise((resolve, reject) => {
    const recognition = new Recognition();
    active = recognition;
    recognition.lang = language === "tr" ? "tr-TR" : language === "en" ? "en-US" : (navigator.language || "en-US");
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.continuous = false;
    let settled = false;
    recognition.onresult = (event) => {
      const best = event.results[0]?.[0];
      settled = true;
      if (best?.transcript.trim()) resolve({ text: best.transcript.trim(), confidence: best.confidence ?? null, engine });
      else reject(new Error("No speech was recognized."));
    };
    recognition.onerror = (event) => {
      if (settled) return;
      settled = true;
      reject(new Error(event.error === "not-allowed" ? "Microphone permission was denied." : `Speech recognition failed (${event.error}).`));
    };
    recognition.onend = () => {
      active = null;
      if (!settled) reject(new Error("No speech was recognized."));
    };
    recognition.start();
  });
}

export function stopListening(): void {
  try { active?.abort(); } catch { /* already stopped */ }
  active = null;
}

/** Speak AKASHI's reply on the device (on-device synthesis). */
export function speak(text: string): void {
  if (typeof window === "undefined" || !window.speechSynthesis || !text.trim()) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text.slice(0, 400));
  utterance.lang = /[çğıöşüİ]/iu.test(text) ? "tr-TR" : "en-US";
  window.speechSynthesis.speak(utterance);
}
