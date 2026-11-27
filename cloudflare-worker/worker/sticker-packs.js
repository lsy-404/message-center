const MAX_PACKS = 20;
const MAX_IMAGES_PER_PACK = 100;
const MAX_NAME_CHARS = 20;
const MAX_IMAGE_BYTES = 3 * 1024 * 1024;
const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);

const now = () => new Date().toISOString();

async function sha256Hex(bytes) {
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
    .map((value) => value.toString(16).padStart(2, "0")).join("");
}

function packName(value) {
  const name = typeof value === "string" ? value.normalize("NFKC").replace(/\s+/g, " ").trim() : "";
  if (!name || [...name].length > MAX_NAME_CHARS) throw new Error("invalid_pack_name");
  return name;
}

function imagePayload(row) {
  return { id: row.id, fileName: row.file_name, mimeType: row.mime_type, sizeBytes: row.size_bytes, sha256: row.sha256 };
}

async function requirePack(env, packId) {
  const pack = await env.DB.prepare("SELECT id, name FROM sticker_packs WHERE id = ?").bind(packId).first();
  if (!pack) throw new Error("sticker_pack_not_found");
  return pack;
}

async function readPacks(env) {
  const [packs, images] = await Promise.all([
    env.DB.prepare("SELECT id, name FROM sticker_packs ORDER BY position, created_at").all(),
    env.DB.prepare("SELECT * FROM sticker_pack_images ORDER BY position, created_at").all(),
  ]);
  const byPack = new Map();
  for (const row of images.results || []) {
    const list = byPack.get(row.pack_id) || [];
    list.push(imagePayload(row));
    byPack.set(row.pack_id, list);
  }
  return (packs.results || []).map((pack) => ({ id: pack.id, name: pack.name, images: byPack.get(pack.id) || [] }));
}

export async function stickerPackObjectKeys(env) {
  const rows = await env.DB.prepare("SELECT object_key FROM sticker_pack_images").all();
  return (rows.results || []).map((row) => row.object_key);
}

// Stores bytes under a fresh key and records the image; a repeated image in the same pack returns the existing row.
async function addImage(env, packId, fileName, mimeType, bytes) {
  await requirePack(env, packId);
  if (!IMAGE_TYPES.has(mimeType)) throw new Error("invalid_image_type");
  if (bytes.byteLength < 1 || bytes.byteLength > MAX_IMAGE_BYTES) throw new Error("invalid_image_size");
  const digest = await sha256Hex(bytes);
  const existing = await env.DB.prepare("SELECT * FROM sticker_pack_images WHERE pack_id = ? AND sha256 = ?")
    .bind(packId, digest).first();
  if (existing) return { image: imagePayload(existing), created: false };
  const total = await env.DB.prepare("SELECT COUNT(*) AS total, COALESCE(MAX(position), 0) AS last FROM sticker_pack_images WHERE pack_id = ?")
    .bind(packId).first();
  if (Number(total?.total) >= MAX_IMAGES_PER_PACK) throw new Error("sticker_pack_full");
  const id = crypto.randomUUID();
  const objectKey = `sticker-packs/${id}`;
  await env.FILES.put(objectKey, bytes, { httpMetadata: { contentType: mimeType }, customMetadata: { sha256: digest } });
  try {
    await env.DB.prepare(`
      INSERT INTO sticker_pack_images (id, pack_id, object_key, file_name, mime_type, size_bytes, sha256, position, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(id, packId, objectKey, fileName, mimeType, bytes.byteLength, digest, Number(total?.last || 0) + 1, now()).run();
  } catch (error) {
    await env.FILES.delete(objectKey).catch(() => {});
    throw error;
  }
  return {
    image: { id, fileName, mimeType, sizeBytes: bytes.byteLength, sha256: digest },
    created: true,
  };
}

async function createPack(request, env, identity, h) {
  const body = await h.readJson(request, 4 * 1024);
  const name = packName(body?.name);
  const total = await env.DB.prepare("SELECT COUNT(*) AS total, COALESCE(MAX(position), 0) AS last FROM sticker_packs").first();
  if (Number(total?.total) >= MAX_PACKS) throw new Error("too_many_sticker_packs");
  const id = crypto.randomUUID();
  const stamp = now();
  await env.DB.prepare("INSERT INTO sticker_packs (id, name, position, created_at, updated_at) VALUES (?, ?, ?, ?, ?)")
    .bind(id, name, Number(total?.last || 0) + 1, stamp, stamp).run();
  await h.audit(env, identity.id, "sticker_pack_created", id, { name });
  return h.json({ ok: true, pack: { id, name, images: [] } }, 201);
}

async function renamePack(request, env, identity, h, packId) {
  const name = packName((await h.readJson(request, 4 * 1024))?.name);
  await requirePack(env, packId);
  await env.DB.prepare("UPDATE sticker_packs SET name = ?, updated_at = ? WHERE id = ?").bind(name, now(), packId).run();
  await h.audit(env, identity.id, "sticker_pack_renamed", packId, { name });
  return h.json({ ok: true });
}

async function reorderPacks(request, env, identity, h) {
  const ids = (await h.readJson(request, 8 * 1024))?.ids;
  const current = ((await env.DB.prepare("SELECT id FROM sticker_packs").all()).results || []).map((row) => row.id);
  if (!Array.isArray(ids) || ids.length !== current.length || new Set(ids).size !== ids.length ||
      !ids.every((id) => current.includes(id))) throw new Error("invalid_pack_order");
  await env.DB.batch(ids.map((id, index) =>
    env.DB.prepare("UPDATE sticker_packs SET position = ? WHERE id = ?").bind(index + 1, id)));
  await h.audit(env, identity.id, "sticker_packs_reordered", null, {});
  return h.json({ ok: true });
}

async function deletePack(env, identity, h, packId) {
  await requirePack(env, packId);
  const keys = ((await env.DB.prepare("SELECT object_key FROM sticker_pack_images WHERE pack_id = ?").bind(packId).all())
    .results || []).map((row) => row.object_key);
  await env.DB.batch([
    env.DB.prepare("DELETE FROM sticker_pack_images WHERE pack_id = ?").bind(packId),
    env.DB.prepare("DELETE FROM sticker_packs WHERE id = ?").bind(packId),
  ]);
  if (keys.length) await env.FILES.delete(keys).catch(() => {});
  await h.audit(env, identity.id, "sticker_pack_deleted", packId, { images: keys.length });
  return h.json({ ok: true });
}

async function uploadImage(request, env, identity, h, packId) {
  if (Number(request.headers.get("content-length") || 0) > MAX_IMAGE_BYTES + 512 * 1024) throw new Error("request_too_large");
  const file = (await request.formData()).get("file");
  if (!(file instanceof File)) throw new Error("invalid_image_size");
  const bytes = await file.arrayBuffer();
  const mimeType = h.imageMime(new Uint8Array(bytes));
  const result = await addImage(env, packId, h.cleanName(file.name, "sticker"), mimeType, bytes);
  if (result.created) await h.audit(env, identity.id, "sticker_image_added", result.image.id, { packId });
  return h.json({ ok: true, image: result.image }, result.created ? 201 : 200);
}

async function collectAttachment(request, env, identity, h, packId) {
  const attachmentId = (await h.readJson(request, 4 * 1024))?.attachmentId;
  const row = typeof attachmentId === "string" ? await env.DB.prepare(`
    SELECT object_key, file_name FROM attachments
    WHERE id = ? AND message_id IS NOT NULL AND object_key IS NOT NULL
  `).bind(attachmentId).first() : null;
  if (!row) throw new Error("attachment_not_found");
  const object = await env.FILES.get(row.object_key);
  if (!object) throw new Error("attachment_not_found");
  const bytes = await object.arrayBuffer();
  const mimeType = h.imageMime(new Uint8Array(bytes));
  const result = await addImage(env, packId, h.cleanName(row.file_name, "sticker"), mimeType, bytes);
  if (result.created) await h.audit(env, identity.id, "sticker_image_collected", result.image.id, { packId, attachmentId });
  return h.json({ ok: true, image: result.image }, result.created ? 201 : 200);
}

async function removeImage(env, identity, h, packId, imageId) {
  const row = await env.DB.prepare("SELECT object_key FROM sticker_pack_images WHERE id = ? AND pack_id = ?")
    .bind(imageId, packId).first();
  if (!row) throw new Error("sticker_image_not_found");
  await env.DB.prepare("DELETE FROM sticker_pack_images WHERE id = ?").bind(imageId).run();
  await env.FILES.delete(row.object_key).catch(() => {});
  await h.audit(env, identity.id, "sticker_image_removed", imageId, { packId });
  return h.json({ ok: true });
}

async function downloadImage(env, h, imageId) {
  const row = await env.DB.prepare("SELECT * FROM sticker_pack_images WHERE id = ?").bind(imageId).first();
  if (!row) throw new Error("sticker_image_not_found");
  const object = await env.FILES.get(row.object_key);
  if (!object) throw new Error("sticker_image_not_found");
  return new Response(object.body, { headers: {
    "content-type": row.mime_type, "content-length": String(row.size_bytes),
    "content-disposition": `inline; filename*=UTF-8''${encodeURIComponent(row.file_name)}`,
    "cache-control": "private, max-age=86400", "x-content-type-options": "nosniff",
  }});
}

// Returns a Response for sticker-pack routes, or null when the path is not one of them.
// h: { json, readJson, audit, imageMime, cleanName } from the Worker entry.
export async function handleStickerPackRoute(request, env, identity, url, h) {
  const { pathname } = url;
  const method = request.method;
  const image = pathname.match(/^\/api\/sticker-images\/([a-zA-Z0-9-]+)$/);
  if (image && method === "GET") return await downloadImage(env, h, image[1]);
  if (!pathname.startsWith("/api/sticker-packs")) return null;
  if (pathname === "/api/sticker-packs") {
    if (method === "GET") return h.json({ ok: true, packs: await readPacks(env) });
    if (method === "POST") return await createPack(request, env, identity, h);
  }
  if (pathname === "/api/sticker-packs/order" && method === "PUT") return await reorderPacks(request, env, identity, h);
  const pack = pathname.match(/^\/api\/sticker-packs\/([a-zA-Z0-9-]+)$/);
  if (pack && method === "PUT") return await renamePack(request, env, identity, h, pack[1]);
  if (pack && method === "DELETE") return await deletePack(env, identity, h, pack[1]);
  const images = pathname.match(/^\/api\/sticker-packs\/([a-zA-Z0-9-]+)\/images$/);
  if (images && method === "POST") return await uploadImage(request, env, identity, h, images[1]);
  const collected = pathname.match(/^\/api\/sticker-packs\/([a-zA-Z0-9-]+)\/images\/from-attachment$/);
  if (collected && method === "POST") return await collectAttachment(request, env, identity, h, collected[1]);
  const one = pathname.match(/^\/api\/sticker-packs\/([a-zA-Z0-9-]+)\/images\/([a-zA-Z0-9-]+)$/);
  if (one && method === "DELETE") return await removeImage(env, identity, h, one[1], one[2]);
  return null;
}
