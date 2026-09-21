import type { ResearchResult, ResearchSource } from "./absolute-api";

export type CenterStageType =
  | "core"
  | "product"
  | "video"
  | "research"
  | "image"
  | "vision"
  | "system"
  | "document"
  | "intelligence";

export type CenterStageMetadata = {
  label: string;
  value: string;
};

export type CenterStageEntity = {
  type: CenterStageType;
  title: string;
  subtitle: string;
  image?: string;
  metadata: CenterStageMetadata[];
  sources: ResearchSource[];
  confidence: "high" | "medium" | "limited";
  contextId: string;
};

const productTerms = /\b(gpu|ekran kartı|telefon|laptop|notebook|ürün|product|edition|anniversary|rog|geforce|radeon|iphone|galaxy|pixel|thinkpad|macbook)\b/iu;

function confidenceFor(result: ResearchResult): CenterStageEntity["confidence"] {
  if (result.sources.length >= 4 && result.synthesis_status === "completed") return "high";
  if (result.sources.length >= 2) return "medium";
  return "limited";
}

export function stageFromResearch(result: ResearchResult): CenterStageEntity {
  const product = productTerms.test(result.question);
  const video = /\b(video|youtube|watch)\b/iu.test(result.question);
  const metadata = result.findings.slice(0, 4).map((finding, index) => ({
    label: `FINDING ${String(index + 1).padStart(2, "0")}`,
    value: finding.finding,
  }));
  return {
    type: video ? "video" : product ? "product" : "research",
    title: result.question,
    subtitle: result.sources.length ? result.summary || result.findings[0]?.finding || "Kaynak sentezi tamamlandı." : "Kaynak bulunamadı. Konuyu daralt veya araştırma sağlayıcısını kontrol et.",
    metadata,
    sources: result.sources,
    confidence: confidenceFor(result),
    contextId: `research:${crypto.randomUUID()}`,
  };
}

/** No executable/custom protocol, credentials or local file may leave a result card. */
export function publicSourceUrl(value: string): string | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    return url.href;
  } catch { return null; }
}
