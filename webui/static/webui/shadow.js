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
 * The store is in-memory (durable browser storage is upstream
 * NEDB Phase 2): a closed tab loses an undrained tail — the
 * drain debounce is 250 ms, so the exposure is a fraction of a
 * second of desk work, stated plainly rather than hidden. If
 * the wasm cannot load at all, this module never becomes ready
 * and the day book runs its server path exactly as before: the
 * book never depends on the shadow.
 *
 * Seam: CustomEvents on document (os:pack in, os:op in,
 * os:record / os:drain / os:undo-move / os:shadow-ready out),
 * plus window.OpenSalonShadow for state queries.
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
  } catch (err) {
    document.body.dataset.shadow = "unavailable";
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
    });
  });
}

function enqueue(op) {
  const key = opKey();
  db.put(
    "outbox",
    key,
    JSON.stringify(Object.assign({ state: "queued", at: Date.now() }, op))
  );
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

async function drain() {
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

document.addEventListener("os:pack", function (event) { seed(event.detail); });
document.addEventListener("os:op", function (event) { applyLocal(event.detail); });
document.addEventListener("os:undo", function () { undo(); });

window.OpenSalonShadow = {
  get ready() { return ready; },
  verify: function () { return ready ? db.verify() : false; },
  seq: function () { return ready ? db.seq() : 0; },
  pending: function () { return queuedIds.length; },
  undoDepth: function () { return undoStack.length; },
};

boot();
