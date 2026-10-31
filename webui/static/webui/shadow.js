/* OpenSalon embedded store — NEDB (nedb-wasm) as the app itself.
 *
 * The founder's two-stage design:
 *
 *   Stage 1 (here): the embedded NEDB in the tab IS the app.
 *   Page load is the recovery — the pack hydrates the store —
 *   and from then on every user action records here first: the
 *   appointment doc is rewritten in the store's hash chain (the
 *   DAG of in-memory plays), the screen repaints from it, and
 *   the op lands in the `outbox` collection. Nothing in the
 *   click path waits on HTTP.
 *
 *   Stage 2 (http nedbv2 behind the Django server): persistence
 *   only. The outbox drains to it in bulk batches
 *   (POST /daybook/apply/) on its own schedule — it proves and
 *   keeps, it never gates the UI. A drained op is marked acked
 *   in the chain; a rejected op is marked failed with the
 *   server's reason, and the client re-reads the truth.
 *
 * The store's chain is PRESERVED in the app, as the founder's
 * design states: not only the queue but the journal itself
 * and the docs it folds to are mirrored into the app's own
 * durable memory (IndexedDB under this module) the moment
 * they are written, and struck off only when they are
 * superseded or the server has spoken. At boot the preserved
 * chain is restored into the store BEFORE the node's word
 * arrives — the app answers from its own database first, and
 * the pack reconciles behind it (the chain law at boot, as
 * everywhere). HTTP recovery is what remains for a store that
 * was never preserved; it is the fallback, not the mechanism.
 * Docs outside the book's working window (a fortnight either
 * side of today) are pruned at restore. A pagehide tries one
 * last keepalive drain on the way out. State ops replay
 * exactly; an add-note whose ack died with the tab is
 * recognised server-side by its identical body on the same
 * target and not written twice. If IndexedDB is unavailable
 * the mirrors quietly no-op and the store is session-bound.
 * If the wasm cannot load at all, this module never becomes
 * ready and the day book runs its server path exactly as
 * before: the book never depends on the shadow.
 *
 * Seam: CustomEvents on document (os:pack / os:adopt / os:op /
 * os:put / os:create in, os:record / os:vanish / os:rename /
 * os:drain / os:undo-move / os:shadow-ready / os:restored /
 * os:recovered out), plus window.OpenSalonShadow for state
 * queries.
 *
 * The chain, as the founder states it: fetches answer from
 * this store first, then chain to the HTTP node — the node's
 * answer arrives as an ADOPT: the pack's days reconcile INTO
 * the store (docs land or vanish here), and the render model
 * follows the store's word via os:record / os:vanish, never
 * the other way around. Writes run the chain in reverse: a
 * play records here, drains to the node, and the node's
 * persisted word chains back in through the next adopt.
 */
const engineUrl = new URL("nedb/nedb_wasm.js", import.meta.url);

let db = null;
let ready = false;
let seededVersion = "";
const undoStack = [];
const queuedIds = [];
let drainTimer = null;
let draining = false;

function emit(name, detail) {
  document.dispatchEvent(new CustomEvent(name, { detail: detail || {} }));
}

function opKey() {
  return "op_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
}

async function boot() {
  try {
    const mod = await import(engineUrl.href);
    await mod.default();
    db = new mod.NedbWasm();
    /* The preserved chain comes home first: docs and journal
       restored from the app's own durable memory before the
       store declares itself, so the first answer this tab
       gives is its own. Births that outlived their tab are
       spoken for at once — a block the desk made is on the
       book when the book opens, not when the node replies. */
    const restored = await restorePreserved();
    ready = true;
    document.body.dataset.shadow = "live";
    emit("os:shadow-ready", { verify: db.verify(), restored: restored });
    recoverQueue();
    restored.births.forEach(function (doc) { emit("os:record", doc); });
    if (restored.docs || restored.journal) {
      emit("os:restored", {
        docs: restored.docs, journal: restored.journal,
      });
    }
  } catch (err) {
    document.body.dataset.shadow = "unavailable";
  }
}

/* ---- the durable memory queue (IndexedDB mirror) ---- */

let idbPromise = null;

function idbOpen() {
  if (idbPromise) return idbPromise;
  idbPromise = new Promise(function (resolve) {
    try {
      const req = indexedDB.open("opensalon-shadow", 2);
      req.onupgradeneeded = function () {
        const handle = req.result;
        /* v1 held the queue alone; v2 preserves the whole
           chain — the docs and the journal beside the outbox. */
        ["outbox", "docs", "journal"].forEach(function (name) {
          if (!handle.objectStoreNames.contains(name)) {
            handle.createObjectStore(name, { keyPath: "key" });
          }
        });
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { resolve(null); };
    } catch (err) {
      resolve(null);
    }
  });
  return idbPromise;
}

async function idbPutIn(store, key, rec) {
  const handle = await idbOpen();
  if (!handle) return;
  try {
    handle
      .transaction(store, "readwrite")
      .objectStore(store)
      .put(Object.assign({ key: key }, rec));
  } catch (err) {
    /* Durability is layered under the living store, never
       load-bearing: a failed mirror write loses nothing the
       store itself still holds. */
  }
}

async function idbDeleteIn(store, key) {
  const handle = await idbOpen();
  if (!handle) return;
  try {
    handle
      .transaction(store, "readwrite")
      .objectStore(store)
      .delete(key);
  } catch (err) {
    /* A record that survives its moment is pruned on a later
       boot's recovery pass if it is no longer wanted there. */
  }
}

function idbPut(key, rec) { return idbPutIn("outbox", key, rec); }
function idbDelete(key) { return idbDeleteIn("outbox", key); }

async function idbAll(store) {
  const handle = await idbOpen();
  if (!handle) return [];
  return new Promise(function (resolve) {
    try {
      const out = [];
      const req = handle
        .transaction(store, "readonly")
        .objectStore(store)
        .openCursor();
      req.onsuccess = function () {
        const cursor = req.result;
        if (cursor) {
          out.push(cursor.value);
          cursor.continue();
        } else {
          resolve(out);
        }
      };
      req.onerror = function () { resolve([]); };
    } catch (err) {
      resolve([]);
    }
  });
}

function idbQueued() { return idbAll("outbox"); }

/* ---- preservation: the chain, kept in the app ---- */

/* Every doc write goes through here, so the preserved copy
   can never drift from the living one: the mirror is struck
   in the same breath as the store write. */
function putDoc(id, doc) {
  const json = JSON.stringify(doc);
  db.put("appointments", String(id), json);
  idbPutIn("docs", String(id), { doc: json });
}

function delDoc(id) {
  try { db.delete("appointments", String(id)); } catch (err) {}
  idbDeleteIn("docs", String(id));
}

/* The journal is append-only: entries are written once and
   never struck — the chain is the provenance, kept whole. */
function journal(op) {
  const key = opKey();
  const json = JSON.stringify(Object.assign({ at: Date.now() }, op));
  db.put("ops", key, json);
  idbPutIn("journal", key, { op: json });
}

/* Boot's first act: the preserved docs and journal come home
   into the fresh engine. Docs outside the book's working
   window (a fortnight either side of today) are pruned from
   both stores — the book keeps what it works with, not an
   archive. Unacked births are collected so boot can speak
   for them the moment the store is ready. */
async function restorePreserved() {
  const out = { docs: 0, journal: 0, births: [] };
  const today = new Date();
  function isoDays(delta) {
    const d = new Date(today.getTime() + delta * 86400000);
    return d.toISOString().slice(0, 10);
  }
  const lo = isoDays(-14), hi = isoDays(14);
  const docs = await idbAll("docs");
  docs.forEach(function (rec) {
    if (!rec.doc) return;
    let doc = null;
    try { doc = JSON.parse(rec.doc); } catch (err) { return; }
    if (!doc || !doc.day) return;
    if (doc.day < lo || doc.day > hi) {
      idbDeleteIn("docs", rec.key);
      return;
    }
    db.put("appointments", String(doc.id), rec.doc);
    indexDoc(doc.day, doc.id);
    out.docs += 1;
    if (String(doc.id).indexOf("tmp_") === 0) out.births.push(doc);
  });
  const entries = await idbAll("journal");
  entries.forEach(function (rec) {
    if (!rec.op) return;
    db.put("ops", rec.key, rec.op);
    out.journal += 1;
  });
  return out;
}

async function recoverQueue() {
  const saved = await idbQueued();
  const queued = saved
    .filter(function (rec) { return rec.state === "queued"; })
    .sort(function (a, b) { return (a.at || 0) - (b.at || 0); });
  /* Anything mirrored but no longer queued was spoken for in
     a life this tab never saw finish; the server already has
     its word, so the mirror lets it go. */
  saved.forEach(function (rec) {
    if (rec.state !== "queued") idbDelete(rec.key);
  });
  queued.forEach(function (rec) {
    const clean = Object.assign({}, rec);
    const key = clean.key;
    delete clean.key;
    db.put("outbox", key, JSON.stringify(clean));
    if (queuedIds.indexOf(key) < 0) queuedIds.push(key);
  });
  if (queued.length) {
    emit("os:recovered", { count: queued.length });
    scheduleDrain(800);
  }
}

/* ---- stage 1: recovery + local plays ---- */

function seed(pack) {
  if (!ready || !pack || !pack.days || pack.version === seededVersion) return;
  seededVersion = pack.version;
  Object.keys(pack.days).forEach(function (iso) {
    pack.days[iso].forEach(function (entry) {
      putDoc(entry.id, Object.assign({ day: iso }, entry));
      delete contestedAt[entry.id];
      indexDoc(iso, entry.id);
    });
  });
}

/* Which appointment ids live on which day, as this store
   knows it. A doc lives on exactly one day: indexing it
   anywhere strips it from every other day's set, so a
   cross-day move can never be deleted by its old day's
   reconcile after its new day has adopted it. */
const dayIndex = {};

function indexDoc(iso, id) {
  Object.keys(dayIndex).forEach(function (d) {
    if (d !== iso && dayIndex[d]) delete dayIndex[d][id];
  });
  (dayIndex[iso] = dayIndex[iso] || {})[id] = true;
}

/* The node's answer, reconciled in: for each day the pack
   speaks for, every entry lands as a doc (os:record carries
   it to the render model, which follows the store), and any
   doc the day no longer holds vanishes — deleted here, and
   os:vanish takes it out of the model. Nothing here queues
   an op: adoption is the node's word arriving, not a play. */
function adopt(days) {
  if (!ready || !days) return;
  Object.keys(days).forEach(function (iso) {
    const keep = {};
    (days[iso] || []).forEach(function (entry) {
      const doc = Object.assign({ day: iso }, entry);
      putDoc(entry.id, doc);
      /* The node's fresh word IS the rebase: the contested
         hold on this doc lifts, and its tail replays onto
         the base that just landed. */
      delete contestedAt[entry.id];
      indexDoc(iso, entry.id);
      keep[entry.id] = true;
      emit("os:record", doc);
    });
    const known = dayIndex[iso] || {};
    Object.keys(known).forEach(function (id) {
      if (id.indexOf("tmp_") === 0) {
        /* A store-born booking the node has not named yet is
           not the node's to vanish — its create is still in
           the queue, and its own ack will settle it. */
        keep[id] = true;
        return;
      }
      if (!keep[id]) {
        delDoc(id);
        delete known[id];
        emit("os:vanish", { day: iso, id: parseInt(id, 10) });
      }
    });
  });
}

function enqueue(op) {
  const key = opKey();
  const rec = Object.assign({ state: "queued", at: Date.now() }, op);
  db.put("outbox", key, JSON.stringify(rec));
  idbPut(key, rec);
  queuedIds.push(key);
  scheduleDrain(250);
  return key;
}

/* The journal's edges, made explicit — the DAG in data:
   a play on a store-born doc names the birth it depends on
   (`after` = the create's queue key, persisted with the op,
   so the edge survives the tab too). The drain honors edges
   per doc: an op rides only once its dependency has drained
   or stands named; ops on OTHER docs are independent and
   flow past a held one — a chain per doc, a DAG across the
   book, never one global lockstep. */
const birthKeys = {};

function enqueuePlay(wire) {
  if (typeof wire.id === "string" && birthKeys[wire.id]) {
    wire.after = birthKeys[wire.id];
  }
  return enqueue(wire);
}

/* Contested docs: the node rejected a play on a doc, so the
   doc's local base is in doubt. Its queued tail is HELD —
   not struck — while the node's fresh word is fetched; the
   adopt that lands replaces the base and the tail replays
   onto it (a rebase, not a reload). The hold carries a
   TTL: a doc the node never speaks for again within ten
   seconds stands as it is, and its plays drain to the
   server's own arbitration rather than waiting forever. */
const contestedAt = {};

function contested(id) {
  const at = contestedAt[id];
  return at != null && Date.now() - at < 10000;
}

function applyLocal(op) {
  if (!ready || !op || !op.id) return;
  const raw = db.get("appointments", String(op.id));
  if (op.kind === "move") {
    if (raw) {
      const doc = JSON.parse(raw);
      const dur = doc.end_min - doc.start_min;
      doc.staff_id = op.after.staff_id;
      doc.start_min = op.after.start_min;
      doc.end_min = op.after.start_min + dur;
      putDoc(op.id, doc);
      emit("os:record", doc);
    }
    if (!op.via) undoStack.push(op);
    enqueuePlay({
      kind: "move",
      id: op.id,
      staff_member_id: op.after.staff_id,
      start_minutes: op.after.start_min,
    });
  } else if (op.kind === "status") {
    if (raw) {
      const doc = JSON.parse(raw);
      doc.status = op.status;
      putDoc(op.id, doc);
      emit("os:record", doc);
    }
    enqueuePlay({ kind: "status", id: op.id, status: op.status });
  } else if (op.kind === "price") {
    if (raw) {
      const doc = JSON.parse(raw);
      /* The card's price becomes the doc's amount at once; the
         label mirrors the server's rule (whole dollars whole).
         Clearing hands the amount back to the book — the doc
         keeps its last true label until the drain's re-stamp
         brings the book's word. */
      if (op.price !== "" && op.price != null) {
        doc.amount = String(op.price);
        const v = parseFloat(op.price);
        doc.price_label = isNaN(v)
          ? doc.price_label
          : v === Math.trunc(v)
            ? "$" + Math.trunc(v)
            : "$" + v.toFixed(2);
      }
      doc.price_overridden = op.price !== "" && op.price != null;
      putDoc(op.id, doc);
      emit("os:record", doc);
    }
    enqueuePlay({ kind: "price", id: op.id, price: op.price == null ? "" : String(op.price) });
  } else if (op.kind === "note") {
    /* Notes live on the card, not in the appointment doc: the
       play is journaled and queued like every other, and the
       card re-reads its payloads when the drain acks. */
    enqueuePlay({
      kind: "note",
      id: op.id,
      scope: op.scope,
      note_id: op.note_id == null ? null : op.note_id,
      body: op.body,
    });
  }
  /* Every op is journaled whether it drains or not — the
     chain is the provenance of the desk's plays. */
  journal(op);
}

/* Temporary birth names and the real ids the node answers
   with: a store-born doc lives under its ref until its create
   drains, and every play chained onto it rides under the ref
   too — the drain substitutes the real id once it is known,
   and holds a batch that would outrun the birth. */
const renames = {};

/* A booking is born here, in the same frame as the gesture —
   the last write that still waited on the node. The doc is
   the desk's own facts (who, what, when) under a temporary
   ref; the create play queues behind it and drains like any
   other, and the node's answer renames the doc to its real
   id and replaces it with the true pack entry. The click
   path holds no HTTP: if the drain later fails, the node
   refused the birth and the doc vanishes then. */
function createLocal(detail) {
  if (!ready || !detail || !detail.payload || !detail.doc) return;
  const p = detail.payload;
  const ref = "tmp_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
  const doc = Object.assign({}, detail.doc, {
    id: ref, day: p.date, staff_id: p.staff_member_id,
    status: "booked", visit: ref, local: true,
  });
  putDoc(ref, doc);
  indexDoc(p.date, ref);
  emit("os:record", doc);
  const op = {
    kind: "create", ref: ref,
    staff_member_id: p.staff_member_id, service_id: p.service_id,
    date: p.date, time: p.time,
  };
  if (p.client_id != null) op.client_id = p.client_id;
  if (p.new_client) op.new_client = p.new_client;
  birthKeys[ref] = enqueue(op);
  journal(op);
  detail.handled = true;
}

function undo() {
  if (!ready) return;
  const op = undoStack.pop();
  if (!op) return;
  emit("os:undo-move", {
    id: op.id,
    staff_id: op.before.staff_id,
    start_min: op.before.start_min,
  });
}

/* ---- stage 2: the drain (bulk, on its own schedule) ---- */

function scheduleDrain(ms) {
  if (drainTimer) clearTimeout(drainTimer);
  drainTimer = setTimeout(drain, ms);
}

async function drain(keepalive) {
  if (draining || !ready || !queuedIds.length) return;
  const layout = document.querySelector(".book-layout");
  if (!layout || !layout.dataset.apply) return;
  const tokenEl = layout.querySelector('input[name="csrfmiddlewaretoken"]');
  const batch = [];
  const ops = [];
  let held = 0;
  for (let qi = 0; qi < queuedIds.length && batch.length < 100; qi++) {
    const key = queuedIds[qi];
    const rec = JSON.parse(db.get("outbox", key));
    const op = { kind: rec.kind, id: rec.id };
    let skip = false;
    if (rec.kind === "create") {
      /* The birth itself rides: ref, booking, client. */
      delete op.id;
      op.ref = rec.ref;
      op.staff_member_id = rec.staff_member_id;
      op.service_id = rec.service_id;
      op.date = rec.date;
      op.time = rec.time;
      if (rec.client_id != null) op.client_id = rec.client_id;
      if (rec.new_client) op.new_client = rec.new_client;
    } else if (typeof rec.id === "string" && rec.id.indexOf("tmp_") === 0) {
      /* A play on a booking the node has not named yet: with
         the name known it rides under the real id; without
         it, the play is HELD — its edge (the birth ahead of
         it in this same queue) has not drained. Held is
         per-doc: the book's other docs flow past it. */
      if (renames[rec.id] == null) skip = true;
      else op.id = renames[rec.id];
    }
    /* The edge itself: a play whose birth is still anywhere
       in the queue — ahead of it, or in this very batch —
       waits for a later round. (A wire op serialized beside
       its birth would carry a name the node has not given
       yet.) Once the birth has drained, the rename above
       supplies the real id. The edge is persisted with the
       op, so this holds across a tab's death too. */
    if (!skip && rec.after && queuedIds.indexOf(rec.after) >= 0) {
      skip = true;
    }
    /* A contested doc's tail holds for the node's fresh
       word; the rebase lands when the adopt does. */
    if (!skip && rec.id != null && contested(rec.id)) skip = true;
    if (skip) { held += 1; continue; }
    if (rec.kind === "move") {
      op.staff_member_id = rec.staff_member_id;
      op.start_minutes = rec.start_minutes;
    }
    if (rec.kind === "status") op.status = rec.status;
    if (rec.kind === "price") op.price = rec.price;
    if (rec.kind === "note") {
      op.scope = rec.scope;
      op.note_id = rec.note_id;
      op.body = rec.body;
    }
    batch.push(key);
    ops.push(op);
  }
  if (!batch.length) {
    /* Everything queued is held (an unacked birth, a
       contested tail): say so — the day book hears a drain
       with failures as its cue to fetch the node's word,
       which is exactly what a hold is waiting for. */
    if (held) emit("os:drain", { acked: 0, failed: [{ held: held }] });
    scheduleDrain(900);
    return;
  }
  draining = true;
  try {
    const resp = await fetch(layout.dataset.apply, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": tokenEl ? tokenEl.value : "",
      },
      body: JSON.stringify({ ops: ops }),
      keepalive: !!keepalive,
    });
    const data = await resp.json();
    const failed = [];
    (data.results || []).forEach(function (r, i) {
      const key = batch[i];
      const rec = JSON.parse(db.get("outbox", key));
      rec.state = r.ok ? "acked" : "failed";
      if (!r.ok) {
        rec.error = r.error || "rejected";
        failed.push({ id: rec.id, error: rec.error });
        /* The node refused this play, so its doc's local
           base is in doubt: the doc is contested, and its
           still-queued tail holds for the node's fresh word
           instead of applying onto a rejected state. */
        if (rec.kind === "create") contestedAt[rec.ref] = Date.now();
        else if (rec.id != null) contestedAt[rec.id] = Date.now();
      }
      if (rec.kind === "create") {
        if (r.ok && r.id) {
          /* The node names the birth: the doc takes the real
             id and the node's true entry, and plays chained
             onto the ref resolve through the rename from
             here on. */
          renames[rec.ref] = r.id;
          const wasLocal = !!db.get("appointments", String(rec.ref));
          const entry = r.entry
            ? Object.assign({ day: rec.date }, r.entry)
            : null;
          delDoc(rec.ref);
          if (dayIndex[rec.date]) delete dayIndex[rec.date][rec.ref];
          if (entry) {
            putDoc(r.id, entry);
            indexDoc(rec.date, r.id);
            if (wasLocal) {
              emit("os:rename", {
                from: rec.ref, to: r.id, day: rec.date, entry: entry,
              });
            } else {
              /* Recovered in a fresh tab: the doc was never
                 local — the node's entry simply joins. */
              emit("os:record", entry);
            }
          }
        } else {
          /* The birth was refused: the provisional doc was
             never true — take it off the book. */
          delDoc(rec.ref);
          if (dayIndex[rec.date]) delete dayIndex[rec.date][rec.ref];
          emit("os:vanish", { day: rec.date, id: rec.ref });
        }
      }
      db.put("outbox", key, JSON.stringify(rec));
      /* The server has spoken — acked or failed, this op's
         durable-queue life is over. */
      idbDelete(key);
      const at = queuedIds.indexOf(key);
      if (at >= 0) queuedIds.splice(at, 1);
    });
    emit("os:drain", { acked: batch.length - failed.length, failed: failed });
    if (queuedIds.length) scheduleDrain(400);
  } catch (err) {
    /* The network is down or the server is away: the queue
       waits and retries — the app state never does. */
    scheduleDrain(3000);
  } finally {
    draining = false;
  }
}
setInterval(function () {
  if (queuedIds.length) scheduleDrain(600);
}, 5000);

/* On the way out, one last drain attempt with keepalive —
   best effort only; whatever it cannot land, the IndexedDB
   mirror still holds for the next boot's recovery. */
window.addEventListener("pagehide", function () {
  if (ready && queuedIds.length && !draining) drain(true);
});

document.addEventListener("os:pack", function (event) { seed(event.detail); });
document.addEventListener("os:adopt", function (event) {
  adopt(event.detail && event.detail.days);
});
document.addEventListener("os:op", function (event) { applyLocal(event.detail); });
document.addEventListener("os:create", function (event) { createLocal(event.detail); });
document.addEventListener("os:undo", function () { undo(); });

/* A doc born elsewhere enters the store: a booking the desk
   just made arrives with its pack entry in the server's reply
   (the POST was its persistence — no op is queued for it), and
   the store adopts the doc so every later play on it applies
   here first, like any other. */
document.addEventListener("os:put", function (event) {
  const entry = event.detail;
  if (!ready || !entry || !entry.id || !entry.day) return;
  putDoc(entry.id, entry);
  indexDoc(entry.day, entry.id);
});

window.OpenSalonShadow = {
  get ready() { return ready; },
  verify: function () { return ready ? db.verify() : false; },
  seq: function () { return ready ? db.seq() : 0; },
  pending: function () { return queuedIds.length; },
  undoDepth: function () { return undoStack.length; },
};

boot();
