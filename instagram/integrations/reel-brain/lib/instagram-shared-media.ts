// Signed attachment URLs remain only in memory and are never model input or note data.
export const MAX_SHARED_MEDIA_BYTES = 20 * 1024 * 1024;
const TYPES = new Set(["ig_reel", "reel", "share", "video", "audio", "image"]);
export type SharedSource = { kind: "permalink"; url: string } | { kind: "media"; downloadUrl: string; caption: string };
export function trustedMediaUrl(raw: unknown): URL | undefined {
  if (typeof raw !== "string" || raw.length > 8192) return;
  try {
    const url = new URL(raw);
    if (url.protocol !== "https:" || url.username || url.password || (url.port && url.port !== "443") || url.hostname !== "lookaside.fbsbx.com" || !url.pathname.startsWith("/ig_messaging_cdn/")) return;
    url.hash = "";
    return url;
  } catch { return; }
}
function permalink(value: unknown): string {
  if (typeof value === "string") {
    const match = value.match(/https?:\/\/(?:www\.)?instagram\.com\/(?:p|reel|reels|tv)\/[A-Za-z0-9_-]+(?:\/)?/i);
    return match?.[0] || "";
  }
  if (!value || typeof value !== "object") return "";
  for (const child of Object.values(value)) { const found = permalink(child); if (found) return found; }
  return "";
}
export function sharedSource(message: any): SharedSource | undefined {
  const url = permalink(message);
  if (url) return { kind: "permalink", url };
  for (const attachment of Array.isArray(message?.attachments) ? message.attachments : []) {
    if (!TYPES.has(attachment?.type)) continue;
    const media = trustedMediaUrl(attachment?.payload?.url);
    if (!media) continue;
    const caption = typeof attachment.payload.caption === "string" ? attachment.payload.caption.replace(/https?:\/\/\S+/gi, "[link]").slice(0, 2500) : "";
    return { kind: "media", downloadUrl: media.href, caption };
  }
}
export class SharedMediaError extends Error {
  constructor(public readonly reason: "untrusted_url" | "timeout" | "download_failed" | "redirect_limit" | "too_large" | "unsupported_type" | "empty_media") { super(reason); this.name = "SharedMediaError"; }
}
// Injection is solely for offline tests; the production call uses fetch without auth headers.
export async function downloadSharedMedia(raw: string, fetcher: typeof fetch = fetch): Promise<File> {
  let url = trustedMediaUrl(raw);
  if (!url) throw new SharedMediaError("untrusted_url");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20_000);
  try {
    for (let redirects = 0; redirects <= 3; redirects++) {
      const response = await fetcher(url.href, { redirect: "manual", credentials: "omit", referrerPolicy: "no-referrer", signal: controller.signal });
      if ([301, 302, 303, 307, 308].includes(response.status)) {
        const location = response.headers.get("location");
        await response.body?.cancel();
        if (!location) throw new SharedMediaError("download_failed");
        let next: URL | undefined;
        try { next = trustedMediaUrl(new URL(location, url).href); } catch {}
        if (!next) throw new SharedMediaError("untrusted_url");
        url = next; continue;
      }
      if (!response.ok) { await response.body?.cancel(); throw new SharedMediaError("download_failed"); }
      const type = (response.headers.get("content-type") || "").split(";")[0].trim().toLowerCase();
      const extensions: Record<string, string> = { "video/mp4": "mp4", "video/quicktime": "mov", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/webm": "webm", "video/webm": "webm", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp" };
      if (!extensions[type]) { await response.body?.cancel(); throw new SharedMediaError("unsupported_type"); }
      const length = response.headers.get("content-length");
      if (length && (!/^\d+$/.test(length) || Number(length) > MAX_SHARED_MEDIA_BYTES)) { await response.body?.cancel(); throw new SharedMediaError("too_large"); }
      if (!response.body) throw new SharedMediaError("empty_media");
      const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let total = 0;
      try {
        while (true) {
          const { done, value } = await reader.read(); if (done) break;
          total += value.byteLength;
          if (total > MAX_SHARED_MEDIA_BYTES) { await reader.cancel(); throw new SharedMediaError("too_large"); }
          chunks.push(value);
        }
      } finally { reader.releaseLock(); }
      if (!total) throw new SharedMediaError("empty_media");
      return new File(chunks as BlobPart[], "instagram-shared-media." + extensions[type], { type });
    }
    throw new SharedMediaError("redirect_limit");
  } catch (error) {
    if (error instanceof SharedMediaError) throw error;
    throw new SharedMediaError(controller.signal.aborted ? "timeout" : "download_failed");
  } finally { clearTimeout(timer); }
}
