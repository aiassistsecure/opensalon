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
 * The wasm store is the session's chain; the QUEUE is what
 * outlives the tab. Every queued op is mirrored to IndexedDB
 * the moment it is journaled and struck off only when the
 * server has spoken (acked or failed). At boot the mirror is
 * restored into the outbox and drains on the normal schedule
 * — page load is the recovery for the queue exactly as for
 * the pack, and a pagehide tries one last keepalive drain on
 * the way out. State ops replay exactly; an add-note whose
 * ack died with the tab is recognised server-side by its
 * identical body on the same target and not written twice.
 * If IndexedDB is unavailable the mirror quietly no-ops and
 * the queue is session-bound. If the wasm cannot load at
 * all, this module never becomes ready and the day book runs
 * its server path exactly as before: the book never depends
 * on the shadow.
 *
 * Seam: CustomEvents on document (os:pack / os:adopt / os:op /
 * os:put in, os:record / os:vanish / os:drain / os:undo-move /
 * os:shadow-ready / os:recovered out), plus
 * window.OpenSalonShadow for state queries.
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
    ready = true;
    document.body.dataset.shadow = "live";
    emit("os:shadow-ready", { verify: db.verify() });
    recoverQueue();
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
      const req = indexedDB.open("opensalon-shadow", 1);
      req.onupgradeneeded = function () {
        req.result.createObjectStore("outbox", { keyPath: "key" });
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { resolve(null); };
    } catch (err) {
      resolve(null);
    }
  });
  return idbPromise;
}

async function idbPut(key, rec) {
  const handle = await idbOpen();
  if (!handle) return;
  try {
    handle
      .transaction("outbox", "readwrite")
      .objectStore("outbox")
      .put(Object.assign({ key: key }, rec));
  } catch (err) {
    /* Durability is layered under the session queue, never
       load-bearing: a failed mirror write loses nothing the
       in-memory queue still holds. */
  }
}

async function idbDelete(key) {
  const handle = await idbOpen();
  if (!handle) return;
  try {
    handle
      .transaction("outbox", "readwrite")
      .objectStore("outbox")
      .delete(key);
  } catch (err) {
    /* A record that survives its ack is pruned on a later
       boot's recovery pass if it is no longer queued there;
       a still-queued one is exactly what recovery wants. */
  }
}

async function idbQueued() {
  const handle = await idbOpen();
  if (!handle) return [];
  return new Promise(function (resolve) {
    try {
      const out = [];
      const req = handle
        .transaction("outbox", "readonly")
        .objectStore("outbox")
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
      db.put(
        "appointments",
        String(entry.id),
        JSON.stringify(Object.assign({ day: iso }, entry))
      );
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
      db.put("appointments", String(entry.id), JSON.stringify(doc));
      indexDoc(iso, entry.id);
      keep[entry.id] = true;
      emit("os:record", doc);
    });
    const known = dayIndex[iso] || {};
    Object.keys(known).forEach(function (id) {
      if (!keep[id]) {
        try { db.delete("appointments", String(id)); } catch (err) {}
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
      db.put("appointments", String(op.id), JSON.stringify(doc));
      emit("os:record", doc);
    }
    if (!op.via) undoStack.push(op);
    enqueue({
      kind: "move",
      id: op.id,
      staff_member_id: op.after.staff_id,
      start_minutes: op.after.start_min,
    });
  } else if (op.kind === "status") {
    if (raw) {
      const doc = JSON.parse(raw);
      doc.status = op.status;
      db.put("appointments", String(op.id), JSON.stringify(doc));
      emit("os:record", doc);
    }
    enqueue({ kind: "status", id: op.id, status: op.status });
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
      db.put("appointments", String(op.id), JSON.stringify(doc));
      emit("os:record", doc);
    }
    enqueue({ kind: "price", id: op.id, price: op.price == null ? "" : String(op.price) });
  } else if (op.kind === "note") {
    /* Notes live on the card, not in the appointment doc: the
       play is journaled and queued like every other, and the
       card re-reads its payloads when the drain acks. */
    enqueue({
      kind: "note",
      id: op.id,
      scope: op.scope,
      note_id: op.note_id == null ? null : op.note_id,
      body: op.body,
    });
  }
  /* Every op is journaled whether it drains or not — the
     chain is the provenance of the desk's plays. */
  db.put("ops", opKey(), JSON.stringify(Object.assign({ at: Date.now() }, op)));
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
  const batch = queuedIds.slice(0, 100);
  const ops = batch.map(function (key) {
    const rec = JSON.parse(db.get("outbox", key));
    const op = { kind: rec.kind, id: rec.id };
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
    return op;
  });
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
document.addEventListener("os:undo", function () { undo(); });

/* A doc born elsewhere enters the store: a booking the desk
   just made arrives with its pack entry in the server's reply
   (the POST was its persistence — no op is queued for it), and
   the store adopts the doc so every later play on it applies
   here first, like any other. */
document.addEventListener("os:put", function (event) {
  const entry = event.detail;
  if (!ready || !entry || !entry.id || !entry.day) return;
  db.put("appointments", String(entry.id), JSON.stringify(entry));
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
