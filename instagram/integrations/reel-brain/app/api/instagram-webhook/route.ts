import { forwardInstagramCommerce } from "../../../lib/instagram-commerce";
import { createHmac, timingSafeEqual } from "node:crypto";
import { after } from "next/server";
import { readNotes, saveNote } from "../../../lib/notes";
import { sharedSource, downloadSharedMedia, SharedMediaError, type SharedSource } from "../../../lib/instagram-shared-media";

export const runtime = "nodejs";
const seen = new Set<string>();
// Only fixed classifications and numeric/boolean data are allowed in diagnostics.
function diagnostic(stage: string, details: Record<string, number | boolean> = {}) {
  console.info("instagram-webhook-diagnostic", JSON.stringify({ timestamp: new Date().toISOString(), stage, ...details }));
}

type Incoming = { mid: string; senderId: string; source: SharedSource };

function validSignature(raw: string, header: string | null) {
  const secret = process.env.META_APP_SECRET;
  if (!secret || !header?.startsWith("sha256=")) return false;
  const received = Buffer.from(header.slice(7), "hex");
  const expected = Buffer.from(createHmac("sha256", secret).update(raw).digest("hex"), "hex");
  return received.length === expected.length && timingSafeEqual(received, expected);
}

function events(payload: any): Incoming[] {
  const output: Incoming[] = [];
  const counts = { messagingItems: 0, accountMismatch: 0, accountMissing: 0, echo: 0, unsupportedUrl: 0, supportedUrl: 0, missingIdentifiers: 0, attachmentItems: 0, attachmentUrlRecognized: 0, sharedMediaRecognized: 0 };
  for (const entry of Array.isArray(payload?.entry) ? payload.entry : []) {
    for (const item of Array.isArray(entry?.messaging) ? entry.messaging : []) {
      counts.messagingItems++;
      const hasAttachments = Array.isArray(item?.message?.attachments) && item.message.attachments.length > 0;
      if (hasAttachments) counts.attachmentItems++;
      const source = sharedSource(item?.message);
      if (source) counts.supportedUrl++; else counts.unsupportedUrl++;
      if (source?.kind === "media") counts.sharedMediaRecognized++;
      if (hasAttachments && source) counts.attachmentUrlRecognized++;
      if (!process.env.META_INSTAGRAM_ACCOUNT_ID) { counts.accountMissing++; continue; }
      if (String(item?.recipient?.id || entry?.id) !== process.env.META_INSTAGRAM_ACCOUNT_ID) { counts.accountMismatch++; continue; }
      if (item?.message?.is_echo) { counts.echo++; continue; }
      if (!source) continue;
      if (!item?.message?.mid || !item?.sender?.id) { counts.missingIdentifiers++; continue; }
      output.push({ mid: item.message.mid, senderId: item.sender.id, source });
    }
  }
  diagnostic("event_classification", counts);
  return output;
}

export async function GET(request: Request) {
  const query = new URL(request.url).searchParams;
  if (process.env.META_WEBHOOK_VERIFY_TOKEN && query.get("hub.mode") === "subscribe" && query.get("hub.verify_token") === process.env.META_WEBHOOK_VERIFY_TOKEN) {
    diagnostic("verification_pass");
    return new Response(query.get("hub.challenge") || "", { status: 200 });
  }
  diagnostic("verification_reject");
  return new Response("Verification failed", { status: 403 });
}

export async function POST(request: Request) {
  diagnostic("request_received");
  const raw = await request.text();
  if (!validSignature(raw, request.headers.get("x-hub-signature-256"))) { diagnostic("signature_reject"); return new Response("Invalid signature", { status: 401 }); }
  diagnostic("signature_pass");
  let payload;
  try { payload = JSON.parse(raw); } catch { diagnostic("invalid_json"); return new Response("Invalid JSON", { status: 400 }); }
  if (process.env.INSTAGRAM_COMMERCE_ENABLED === "true") {
    try { const result = await forwardInstagramCommerce(payload); diagnostic("commerce_queued", {count:result.queued}); return Response.json(result); }
    catch { diagnostic("commerce_backend_unavailable"); return Response.json({error:"Commerce temporarily unavailable"},{status:503}); }
  }
  let saved: Set<string>;
  try { saved = new Set((await readNotes()).map(note => note.messageId)); }
  catch { diagnostic("persistence_read_failed"); return new Response("Local storage unavailable", { status: 500 }); }
  let duplicate = 0;
  const incoming = events(payload).filter((event) => {
    if (seen.has(event.mid) || saved.has(event.mid)) { duplicate++; return false; }
    seen.add(event.mid); return true;
  });
  diagnostic("queued", { count: incoming.length, duplicate });
  after(async () => {
    for (const event of incoming) {
      let stage = "analysis";
      try {
      const form = new FormData();
      if (event.source.kind === "permalink") form.set("url", event.source.url);
      else {
        stage = "media_download";
        diagnostic("media_download_start");
        form.set("media", await downloadSharedMedia(event.source.downloadUrl));
        form.set("context", "Shared Instagram media. " + event.source.caption);
        diagnostic("media_download_completed");
      }
      stage = "analysis";
      diagnostic("analysis_start");
      const response = await fetch(new URL("/api/analyze", "http://127.0.0.1:3102"), { method: "POST", body: form });
      const result = await response.json();
      diagnostic("analysis_result", { status: response.status, completed: response.ok });
      if (!response.ok) { seen.delete(event.mid); continue; }
      stage = "persistence";
      const now = new Date().toISOString();
      await saveNote({ messageId: event.mid, sourceUrl: event.source.kind === "permalink" ? event.source.url : "", status: "completed", createdAt: now, updatedAt: now, output: result });
      diagnostic("persistence_saved");
      stage = "reply";
      const accessToken = process.env.INSTAGRAM_ACCESS_TOKEN;
      const accountId = process.env.META_INSTAGRAM_ACCOUNT_ID;
      if (response.ok && accessToken && accountId) {
        const reply = await fetch(`https://graph.instagram.com/${process.env.META_GRAPH_VERSION || "v24.0"}/${accountId}/messages`, {
          method: "POST",
          headers: { authorization: `Bearer ${accessToken}`, "content-type": "application/json" },
          body: JSON.stringify({ recipient: { id: event.senderId }, message: { text: `Saved: ${result.title}\n\n${result.oneSentenceSummary}`.slice(0, 900) } }),
          signal: AbortSignal.timeout(15_000),
        });
        const body = await reply.json().catch(() => ({}));
        diagnostic("reply_result", { accepted: reply.ok && Boolean(body.message_id), status: reply.status, ...(typeof body.error?.code === "number" ? { errorCode: body.error.code } : {}), ...(typeof body.error?.error_subcode === "number" ? { errorSubcode: body.error.error_subcode } : {}) });
      } else diagnostic("reply_settings_missing", { accepted: false });
      } catch (error) { seen.delete(event.mid); diagnostic(stage + "_failed", { completed: false }); if (error instanceof SharedMediaError) diagnostic("media_" + error.reason);

      }
    }
  });
  return Response.json({ received: true, queued: incoming.length });
}
