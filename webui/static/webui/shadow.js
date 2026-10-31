/* OpenSalon client shadow store — embedded NEDB (nedb-wasm).
 *
 * The founder's architecture: nedbd over HTTP is the salon's
 * durable truth; the tab carries an embedded NEDB as a mirror —
 * "shadow writes into the client embedded store for in-memory
 * expansion". This module is that store:
 *
 *   - Every client pack seeds the week's appointments into the
 *     in-memory engine (collection `appointments`).
 *   - Every local operation (a move, a status change) is
 *     journaled as a NEDB write (collection `ops`) in the same
 *     hash chain — the desk's edits carry provenance in the tab,
 *     and `verify()` can re-walk the chain at any moment.
 *   - Undo reads the journal: the last move's `before` state is
 *     still in the chain, so Ctrl+Z restores it exactly.
 *
 * The engine is in-memory only (durable browser storage is
 * upstream Phase 2 in NEDB), which is safe here by design: a
 * mirror may be volatile when it can always re-mirror from the
 * server. If the wasm cannot load — old browser, blocked asset —
 * this module simply never becomes ready, and the day book
 * behaves exactly as it does without a shadow. The book never
 * depends on the shadow.
 *
 * Seam: plain CustomEvents on document. webui.js stays
 * wasm-agnostic; it dispatches os:pack / os:op / os:undo and
 * listens for os:undo-move / os:shadow-ready.
 */
const engineUrl = new URL("nedb/nedb_wasm.js", import.meta.url);

let db = null;
let ready = false;
let seededVersion = "";
const undoStack = [];

function emit(name, detail) {
  document.dispatchEvent(new CustomEvent(name, { detail: detail || {} }));
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

function journal(op) {
  if (!ready || !op || !op.id) return;
  if (op.kind === "move") {
    // Keep the mirrored appointment current with the gesture.
    const raw = db.get("appointments", String(op.id));
    if (raw) {
      const doc = JSON.parse(raw);
      doc.staff_id = op.after.staff_id;
      doc.start_min = op.after.start_min;
      doc.end_min = op.after.start_min + (doc.end_min - doc.start_min);
      db.put("appointments", String(op.id), JSON.stringify(doc));
    }
    if (!op.via) {
      undoStack.push(op);
    }
  }
  db.put(
    "ops",
    "op_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8),
    JSON.stringify(Object.assign({ at: Date.now() }, op))
  );
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

document.addEventListener("os:pack", function (event) { seed(event.detail); });
document.addEventListener("os:op", function (event) { journal(event.detail); });
document.addEventListener("os:undo", function () { undo(); });

window.OpenSalonShadow = {
  get ready() { return ready; },
  verify: function () { return ready ? db.verify() : false; },
  seq: function () { return ready ? db.seq() : 0; },
  undoDepth: function () { return undoStack.length; },
};

boot();
