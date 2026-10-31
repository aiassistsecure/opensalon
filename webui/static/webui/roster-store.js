/* OpenSalon roster store — the embedded NEDB on the roster
 * book, running the founder's chain law on the second surface.
 *
 * The roster book is the day book's controller: patterns are
 * perpetual, overrides rule one date, and the switch decides
 * which a play writes. Its gestures used to post forms and
 * reload the page. Now they record here first:
 *
 *   Stage 1 (here): the roster page hydrates this store from
 *   its seed (HTTP is the recovery — the patterns and the
 *   date's overrides, exactly as rendered). A gesture becomes
 *   a play in the store: the projection repaints the column
 *   from the store's word in the same frame, and the play
 *   lands in the `routbox` queue.
 *
 *   Stage 2 (http nedbv2 behind the Django server): the queue
 *   drains in bulk to POST /roster/apply/ — the cores behind
 *   it are the very ones the old form posts used, switch law
 *   included. A weekly place's answer names the real pattern
 *   id, and plays chained onto a not-yet-acked place wait for
 *   that id rather than guessing. After a drain speaks, the
 *   page's seed is re-fetched and reconciles the store — the
 *   node's word chains back in, as the law runs both ways.
 *
 * The queue is mirrored to IndexedDB the moment a play is
 * journaled and struck off only when the server has spoken,
 * so a closed tab loses no roster play. If the wasm cannot
 * load, this module never becomes ready and the roster book
 * runs its form posts exactly as before: the book never
 * depends on the store.
 *
 * Seam: CustomEvents on document (os:rplay in, os:rstate /
 * os:rdrain / os:roster-ready out), plus window.OpenSalonRoster.
 */
const engineUrl = new URL("nedb/nedb_wasm.js", import.meta.url);

let db = null;
let ready = false;
let seedData = null;
const patternsByKey = {};   /* the projection: pattern key -> doc */
const overridesByMember = {}; /* the projection: member -> override */
const knownMembers = {};
const idmap = {};           /* tmp place ref -> real pattern id */
const queuedKeys = [];
let drainTimer = null;
let draining = false;

function emit(name, detail) {
  document.dispatchEvent(new CustomEvent(name, { detail: detail || {} }));
}

function opKey(prefix) {
  return prefix + "_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
}

function hhmm(mins) {
  return String(Math.floor(mins / 60)).padStart(2, "0") + ":" +
    String(mins % 60).padStart(2, "0");
}

async function boot() {
  try {
    const mod = await import(engineUrl.href);
    await mod.default();
    db = new mod.NedbWasm();
    const seedEl = document.getElementById("roster-seed");
    if (seedEl) {
      try { seedData = JSON.parse(seedEl.textContent); } catch (e) { seedData = null; }
    }
    if (seedData) applySeed(seedData);
    ready = true;
    document.body.dataset.rosterStore = "live";
    emit("os:roster-ready", { verify: db.verify() });
    recoverQueue();
  } catch (err) {
    document.body.dataset.rosterStore = "unavailable";
  }
}

/* ---- hydration: the node's word, taken in ---- */

function applySeed(seed) {
  Object.keys(patternsByKey).forEach(function (k) { delete patternsByKey[k]; });
  Object.keys(overridesByMember).forEach(function (k) { delete overridesByMember[k]; });
  (seed.patterns || []).forEach(function (p) {
    const doc = { id: p.id, member: p.member, start_min: p.start_min, end_min: p.end_min };
    patternsByKey[String(p.id)] = doc;
    db.put("patterns", String(p.id), JSON.stringify(doc));
    knownMembers[p.member] = true;
  });
  Object.keys(seed.overrides || {}).forEach(function (member) {
    const o = seed.overrides[member];
    overridesByMember[member] = {
      is_off: !!o.is_off, start_min: o.start_min, end_min: o.end_min,
    };
    db.put("overrides", String(member), JSON.stringify(overridesByMember[member]));
    knownMembers[member] = true;
  });
  Object.keys(knownMembers).forEach(function (m) { emitState(parseInt(m, 10)); });
}

function resolveMember(member) {
  const ov = overridesByMember[member];
  if (ov) {
    if (ov.is_off) return { member: member, off: true, bands: [] };
    return {
      member: member, off: false,
      bands: [{ start_min: ov.start_min, end_min: ov.end_min, source: "instance", pattern: null }],
    };
  }
  const bands = [];
  Object.keys(patternsByKey).forEach(function (k) {
    const doc = patternsByKey[k];
    if (doc.member === member) {
      bands.push({
        start_min: doc.start_min, end_min: doc.end_min,
        source: "weekly", pattern: doc.id,
      });
    }
  });
  bands.sort(function (a, b) { return a.start_min - b.start_min; });
  return { member: member, off: false, bands: bands };
}

function emitState(member) {
  const state = resolveMember(member);
  state.total_minutes = state.bands.reduce(function (sum, b) {
    return sum + (b.end_min - b.start_min);
  }, 0);
  emit("os:rstate", state);
}

/* ---- the durable queue (IndexedDB mirror) ---- */

let idbPromise = null;

function idbOpen() {
  if (idbPromise) return idbPromise;
  idbPromise = new Promise(function (resolve) {
    try {
      const req = indexedDB.open("opensalon-roster", 1);
      req.onupgradeneeded = function () {
        req.result.createObjectStore("routbox", { keyPath: "key" });
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
    handle.transaction("routbox", "readwrite").objectStore("routbox")
      .put(Object.assign({ key: key }, rec));
  } catch (err) { /* the in-memory queue still holds it */ }
}

async function idbDelete(key) {
  const handle = await idbOpen();
  if (!handle) return;
  try {
    handle.transaction("routbox", "readwrite").objectStore("routbox").delete(key);
  } catch (err) { /* pruned on a later boot's recovery if unqueued */ }
}

async function idbQueued() {
  const handle = await idbOpen();
  if (!handle) return [];
  return new Promise(function (resolve) {
    try {
      const out = [];
      const req = handle.transaction("routbox", "readonly")
        .objectStore("routbox").openCursor();
      req.onsuccess = function () {
        const cursor = req.result;
        if (cursor) { out.push(cursor.value); cursor.continue(); }
        else resolve(out);
      };
      req.onerror = function () { resolve([]); };
    } catch (err) { resolve([]); }
  });
}

async function recoverQueue() {
  const saved = await idbQueued();
  const queued = saved
    .filter(function (rec) { return rec.state === "queued"; })
    .sort(function (a, b) { return (a.at || 0) - (b.at || 0); });
  saved.forEach(function (rec) {
    if (rec.state !== "queued") idbDelete(rec.key);
  });
  queued.forEach(function (rec) {
    const clean = Object.assign({}, rec);
    const key = clean.key;
    delete clean.key;
    db.put("routbox", key, JSON.stringify(clean));
    if (queuedKeys.indexOf(key) < 0) queuedKeys.push(key);
  });
  if (queued.length) scheduleDrain(800);
}

function enqueue(op) {
  const key = opKey("rop");
  const rec = Object.assign({ state: "queued", at: Date.now() }, op);
  db.put("routbox", key, JSON.stringify(rec));
  idbPut(key, rec);
  queuedKeys.push(key);
  scheduleDrain(250);
}

/* ---- plays: recorded here first ---- */

function applyPlay(op) {
  if (!ready || !op || !op.kind || !seedData) return;
  const member = op.member;
  knownMembers[member] = true;
  if (op.kind === "place" && op.weekly) {
    const ref = opKey("tmp");
    const doc = { id: ref, member: member, start_min: op.start_min, end_min: op.end_min };
    patternsByKey[ref] = doc;
    db.put("patterns", ref, JSON.stringify(doc));
    enqueue(Object.assign({}, op, { ref: ref }));
  } else if (op.kind === "place" || (op.kind === "move" && !op.weekly)) {
    overridesByMember[member] = {
      is_off: false, start_min: op.start_min, end_min: op.end_min,
    };
    db.put("overrides", String(member), JSON.stringify(overridesByMember[member]));
    enqueue(op);
  } else if (op.kind === "move" && op.weekly) {
    const key = String(op.pattern);
    const doc = patternsByKey[key];
    if (doc) {
      doc.start_min = op.start_min;
      doc.end_min = op.end_min;
      db.put("patterns", key, JSON.stringify(doc));
    }
    enqueue(op);
  } else if (op.kind === "off" && op.weekly) {
    const key = String(op.pattern);
    delete patternsByKey[key];
    try { db.delete("patterns", key); } catch (err) {}
    enqueue(op);
  } else if (op.kind === "off") {
    overridesByMember[member] = { is_off: true, start_min: null, end_min: null };
    db.put("overrides", String(member), JSON.stringify(overridesByMember[member]));
    enqueue(op);
  } else if (op.kind === "clear") {
    delete overridesByMember[member];
    try { db.delete("overrides", String(member)); } catch (err) {}
    enqueue(op);
  } else {
    return;
  }
  /* Every play is journaled — the chain is the provenance. */
  db.put("rops", opKey("rop"), JSON.stringify(Object.assign({ at: Date.now() }, op)));
  emitState(member);
}

/* ---- the drain: bulk, on its own schedule ---- */

function scheduleDrain(ms) {
  if (drainTimer) clearTimeout(drainTimer);
  drainTimer = setTimeout(drain, ms);
}

function wireOp(rec) {
  const op = {
    kind: rec.kind, member: rec.member, date: seedData.date,
    weekly: !!rec.weekly,
  };
  if (rec.start_min != null) op.start = hhmm(rec.start_min);
  if (rec.end_min != null) op.end = hhmm(rec.end_min);
  if (rec.pattern != null) {
    op.pattern = idmap[rec.pattern] != null ? idmap[rec.pattern] : rec.pattern;
  }
  return op;
}

async function drain() {
  if (draining || !ready || !queuedKeys.length || !seedData) return;
  const tokenEl = document.querySelector('input[name="csrfmiddlewaretoken"]');
  /* A play chained onto a place the node has not acked yet
     waits for the place's real id rather than guessing at
     one: the batch stops before it, and the next round —
     scheduled the moment this one lands — carries it with
     the id filled in. */
  const batch = [];
  for (let i = 0; i < queuedKeys.length && batch.length < 100; i++) {
    const rec = JSON.parse(db.get("routbox", queuedKeys[i]));
    if (rec.pattern != null && typeof rec.pattern === "string" &&
        rec.pattern.indexOf("tmp_") === 0 && idmap[rec.pattern] == null) {
      break;
    }
    batch.push(queuedKeys[i]);
  }
  if (!batch.length) { scheduleDrain(600); return; }
  const ops = batch.map(function (key) {
    return wireOp(JSON.parse(db.get("routbox", key)));
  });
  draining = true;
  try {
    const resp = await fetch(seedData.apply_url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": tokenEl ? tokenEl.value : "",
      },
      body: JSON.stringify({
        ops: ops,
        /* The roster chain's stamp rides like the day
           book's: the node echoes it, and the echo is the
           write-through's receipt. */
        chain: { seq: db.seq(), head: db.head() },
      }),
    });
    const data = await resp.json();
    const failed = [];
    (data.results || []).forEach(function (r, i) {
      const key = batch[i];
      const rec = JSON.parse(db.get("routbox", key));
      rec.state = r.ok ? "acked" : "failed";
      if (!r.ok) {
        rec.error = r.error || "rejected";
        failed.push({ kind: rec.kind, error: rec.error });
      }
      if (r.ok && rec.ref && r.pattern) {
        /* The place has a real name now: the projection's
           doc takes it, and chained plays resolve through
           the map from here on. */
        idmap[rec.ref] = r.pattern;
        const doc = patternsByKey[rec.ref];
        if (doc) {
          delete patternsByKey[rec.ref];
          doc.id = r.pattern;
          patternsByKey[String(r.pattern)] = doc;
          db.put("patterns", String(r.pattern), JSON.stringify(doc));
          try { db.delete("patterns", rec.ref); } catch (err) {}
          emitState(rec.member);
        }
      }
      db.put("routbox", key, JSON.stringify(rec));
      idbDelete(key);
      const at = queuedKeys.indexOf(key);
      if (at >= 0) queuedKeys.splice(at, 1);
    });
    emit("os:rdrain", { acked: batch.length - failed.length, failed: failed });
    if (queuedKeys.length) scheduleDrain(400);
    converge();
  } catch (err) {
    scheduleDrain(3000);
  } finally {
    draining = false;
  }
}
setInterval(function () {
  if (queuedKeys.length) scheduleDrain(600);
}, 5000);

/* The chain's return leg: after the node has spoken, its
   seed reconciles the store. While plays are still queued
   the local word stands — convergence never overwrites an
   undrained gesture. */
async function converge() {
  if (queuedKeys.length) return;
  try {
    const resp = await fetch(window.location.href, {
      headers: { "X-Requested-With": "fetch" },
    });
    const html = await resp.text();
    const doc = new DOMParser().parseFromString(html, "text/html");
    const el = doc.getElementById("roster-seed");
    if (!el) return;
    const fresh = JSON.parse(el.textContent);
    if (fresh && fresh.date === seedData.date) {
      seedData = fresh;
      applySeed(fresh);
    }
  } catch (err) { /* the next drain converges again */ }
}

window.addEventListener("pagehide", function () {
  if (ready && queuedKeys.length && !draining) drain();
});

document.addEventListener("os:rplay", function (event) { applyPlay(event.detail); });

window.OpenSalonRoster = {
  get ready() { return ready; },
  pending: function () { return queuedKeys.length; },
};

boot();
