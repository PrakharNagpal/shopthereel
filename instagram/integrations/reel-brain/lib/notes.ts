import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { join } from "node:path";
export type SavedNote = { messageId: string; sourceUrl: string; status: "completed"; createdAt: string; updatedAt: string; output: { title: string; contentType: string; oneSentenceSummary: string; tags: string[]; keyIdeas: { idea: string; explanation: string }[]; actionItems: string[]; uncertainClaims: string[] } };
const directory = join(process.cwd(), ".local-data");
const path = join(directory, "notes.json");
let pending: Promise<unknown> = Promise.resolve();
export async function readNotes(): Promise<SavedNote[]> {
  try { return JSON.parse(await readFile(path, "utf8")); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return []; throw error; }
}
export function saveNote(note: SavedNote) {
  const operation = pending.then(async () => {
    await mkdir(directory, { recursive: true, mode: 0o700 });
    const notes = await readNotes();
    if (notes.some(item => item.messageId === note.messageId)) return;
    notes.unshift(note);
    const temporary = path + ".tmp";
    await writeFile(temporary, JSON.stringify(notes), { mode: 0o600 });
    await rename(temporary, path);
  });
  pending = operation.catch(() => {});
  return operation;
}
export function isLocalRequest(request: Request) {
  const host = request.headers.get("host") || "";
  return /^(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$/.test(host)
    && (!request.headers.get("x-forwarded-for") || /^(127\.0\.0\.1|::1|::ffff:127\.0\.0\.1)$/.test(request.headers.get("x-forwarded-for") || "")) && !request.headers.has("cf-connecting-ip")
    && (!request.headers.get("origin") || request.headers.get("origin") === new URL(request.url).origin);
}
