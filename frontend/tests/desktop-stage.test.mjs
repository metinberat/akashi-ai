import assert from "node:assert/strict";
import test from "node:test";

import { stageFromResearch, publicSourceUrl } from "../src/lib/desktop-stage.ts";

const sources = Array.from({ length: 4 }, (_, index) => ({
  title: `Primary source ${index + 1}`,
  url: `https://example.test/source-${index + 1}`,
  snippet: "Verified source excerpt.",
  provider: "primary",
  relevance: 0.9,
}));

test("external result links reject executable protocols and embedded credentials", () => {
  for (const value of ["javascript:alert(1)", "file:///C:/private.txt", "https://user:secret@example.test", "akashi://app", "http://example.test", "not-a-url"]) assert.equal(publicSourceUrl(value), null);
  assert.equal(publicSourceUrl("https://example.test/page"), "https://example.test/page");
});

test("video remains source metadata, without inventing a clip, image or confidence", () => {
  const result = { question: "NVIDIA video bul", summary: "", findings: [], sources: [], synthesis_status: "source-only" };
  const first = stageFromResearch(result), second = stageFromResearch(result);
  assert.equal(first.type, "video");
  assert.equal(first.image, undefined);
  assert.match(first.subtitle, /Kaynak bulunamadı/);
  assert.notEqual(first.contextId, second.contextId);
});

test("research results become real-data center stage entities", () => {
  const entity = stageFromResearch({
    question: "Yeni nesil GPU ürününü kaynaklarla karşılaştır",
    mode: "deep",
    provider: "research",
    status: "completed",
    summary: "Dört birincil kaynak aynı ürün ailesini doğruluyor.",
    synthesis_status: "completed",
    findings: [{ title: "Memory", finding: "Bellek kapasitesi üretici sayfasında doğrulandı.", source_url: sources[0].url }],
    sources,
  });

  assert.equal(entity.type, "product");
  assert.equal(entity.confidence, "high");
  assert.equal(entity.sources, sources);
  assert.equal(entity.image, undefined);
  assert.match(entity.metadata[0].value, /doğrulandı/);
});

test("non-product investigations remain research stages", () => {
  const entity = stageFromResearch({
    question: "Kimyasal bağların tarihsel gelişimini araştır",
    mode: "normal",
    provider: "research",
    status: "completed",
    summary: "Kaynak sentezi.",
    synthesis_status: "partial",
    findings: [],
    sources: sources.slice(0, 1),
  });

  assert.equal(entity.type, "research");
  assert.equal(entity.confidence, "limited");
});
