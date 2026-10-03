import { Capacitor } from "@capacitor/core";
import { SpeechRecognition } from "@capgo/capacitor-speech-recognition";

export type VoiceState = "idle" | "listening" | "transcribing" | "thinking" | "acting" | "speaking" | "interrupted" | "error";
let playbackGeneration = 0;

export function nativeVoiceAvailable(): boolean {
  return Capacitor.isNativePlatform() || (typeof window !== "undefined" && Boolean(window.akashiDesktop?.voice));
}

export async function stopNativeVoice(): Promise<void> {
  playbackGeneration += 1;
  if (typeof window !== "undefined") window.speechSynthesis?.cancel();
  const operations: Array<Promise<unknown>> = [
    window.akashiDesktop?.voice.stop().catch(() => undefined) ?? Promise.resolve(),
  ];
  if (Capacitor.isNativePlatform()) {
    operations.push(
      SpeechRecognition.forceStop({ timeout: 750 }).catch(() => undefined),
      import("@capacitor-community/text-to-speech")
        .then(({ TextToSpeech }) => TextToSpeech.stop())
        .catch(() => undefined),
    );
  }
  await Promise.all(operations);
}

export async function recognizeOnce(language: "auto" | "tr" | "en" = "auto", options: { bargeIn?: boolean } = {}): Promise<string> {
  if (!nativeVoiceAvailable()) throw new Error("Native voice is not available.");
  if (window.akashiDesktop?.voice) {
    const result = await window.akashiDesktop.voice.listen({ language, model: "base", bargeIn: options.bargeIn === true });
    const transcript = result.transcript?.trim() || "";
    if (!transcript) throw new Error("Konuşma algılanmadı.");
    return transcript;
  }
  const { available } = await SpeechRecognition.available();
  if (!available) throw new Error("Bu cihazda konuşma tanıma hizmeti bulunamadı.");
  const permission = await SpeechRecognition.requestPermissions();
  if (permission.speechRecognition !== "granted") {
    throw new Error("Mikrofon veya konuşma tanıma izni verilmedi.");
  }
  const result = await SpeechRecognition.start({
    popup: false,
    partialResults: false,
    maxResults: 1,
    language: language === "auto" ? undefined : language === "tr" ? "tr-TR" : "en-US",
    addPunctuation: true,
  });
  const transcript = result.matches?.[0]?.trim() || "";
  if (!transcript) throw new Error("Konuşma algılanmadı. Tekrar deneyebilirsin.");
  return transcript;
}

export async function stopRecognition(): Promise<void> {
  if (window.akashiDesktop?.voice) await window.akashiDesktop.voice.stop();
  else await SpeechRecognition.forceStop({ timeout: 750 });
}

export type SpokenWindowUpdate = { excerpt: string; charIndex: number };

export async function speakNative(text: string, onBoundary?: (update: SpokenWindowUpdate) => void): Promise<void> {
  const generation = ++playbackGeneration;
  if (!nativeVoiceAvailable()) throw new Error("Native voice is not available.");
  const spoken = text.replace(/```[\s\S]*?```/gu, "").replace(/https?:\/\/\S+/gu, "").replace(/[*#`|]/gu, "").trim();
  const sentences = spoken.match(/[^.!?]+[.!?]?/gu) ?? [spoken];
  const excerpt = sentences.slice(0, 2).join(" ").trim().slice(0, 520).replace(/\s+\S*$/u, "");
  if (!excerpt) return;

  if (window.akashiDesktop?.voice) {
    window.speechSynthesis.cancel();
    onBoundary?.({ excerpt, charIndex: 0 });
    await new Promise<void>((resolve, reject) => {
      const utterance = new SpeechSynthesisUtterance(excerpt);
      const language = /[çğıöşüİ]/iu.test(excerpt) ? "tr-TR" : navigator.language || "en-US";
      utterance.lang = language;
      utterance.rate = 1;
      const voices = window.speechSynthesis.getVoices();
      utterance.voice = voices.find((voice) => voice.lang.toLowerCase() === language.toLowerCase())
        || voices.find((voice) => voice.lang.toLowerCase().startsWith(language.slice(0, 2).toLowerCase()))
        || null;
      // The boundary event gives the currently-audible position in the excerpt, so a barge-in
      // candidate can be compared against what's actually playing right now instead of the
      // whole (much longer) excerpt, which would otherwise dilute a real echo's similarity score.
      utterance.onboundary = (event) => onBoundary?.({ excerpt, charIndex: event.charIndex ?? 0 });
      utterance.onend = () => resolve();
      utterance.onerror = (event) => event.error === "interrupted" || event.error === "canceled" ? resolve() : reject(new Error(event.error));
      if (generation !== playbackGeneration) { resolve(); return; }
      window.speechSynthesis.speak(utterance);
    });
    return;
  }
  const { TextToSpeech } = await import("@capacitor-community/text-to-speech");
  await TextToSpeech.stop();
  const deviceLanguage = navigator.language || "tr-TR";
  const preferred = /[çğıöşüİ]/iu.test(text) ? "tr-TR" : deviceLanguage;
  let language = preferred;
  try {
    const { languages } = await TextToSpeech.getSupportedLanguages();
    language = languages.find((item) => item.toLowerCase() === preferred.toLowerCase()) ||
      languages.find((item) => item.toLowerCase().startsWith(preferred.slice(0, 2).toLowerCase())) ||
      languages.find((item) => item.toLowerCase().startsWith(deviceLanguage.slice(0, 2).toLowerCase())) ||
      languages[0] || deviceLanguage;
  } catch {
    // Native TTS chooses a fallback when language enumeration is unavailable.
  }
  if (generation !== playbackGeneration) return;
  if (excerpt) await TextToSpeech.speak({ text: excerpt, lang: language, rate: 1, pitch: 1, volume: 1 });
}

// ── Fast voice path: a persistent Gemini Live Native Audio session (desktop only) ──
// Casual conversation is answered directly, with near-instant native audio.
// Anything requiring a tool, research or memory is handed to AKASHI Core by
// voice/live.py itself (via consult_akashi_core) - this layer only relays the
// resulting lifecycle/transcript events so they can be shown the same way the
// existing voice pipeline's messages are.

export async function liveVoiceAvailable(): Promise<boolean> {
  if (!window.akashiDesktop?.voice.live) return false;
  try {
    return await window.akashiDesktop.voice.live.available();
  } catch {
    return false;
  }
}

export function startLiveVoice(
  language: "auto" | "tr" | "en" = "auto",
  sessionId?: string,
): Promise<{ started: boolean; alreadyRunning?: boolean }> {
  if (!window.akashiDesktop?.voice.live) return Promise.reject(new Error("Live voice is not available."));
  return window.akashiDesktop.voice.live.start({ language, sessionId });
}

export function stopLiveVoice(): Promise<boolean> {
  return window.akashiDesktop?.voice.live.stop() ?? Promise.resolve(false);
}

export function interruptLiveVoice(): Promise<boolean> {
  return window.akashiDesktop?.voice.live.interrupt() ?? Promise.resolve(false);
}

export function sendLiveVoiceText(text: string): Promise<boolean> {
  return window.akashiDesktop?.voice.live.sendText(text) ?? Promise.resolve(false);
}

export function onLiveVoiceEvent(callback: (event: DesktopVoiceLiveEvent) => void): () => void {
  if (!window.akashiDesktop?.voice.live) return () => undefined;
  return window.akashiDesktop.voice.live.onEvent(callback);
}

export async function voiceRuntimeStatus(): Promise<Record<string, unknown>> {
  if (window.akashiDesktop?.voice) return window.akashiDesktop.voice.status();
  if (Capacitor.isNativePlatform()) {
    const available = await SpeechRecognition.available();
    return { engine: "native", available: available.available, wake_word: "foundation-disabled" };
  }
  return { engine: "unavailable", available: false, wake_word: "foundation-disabled" };
}
