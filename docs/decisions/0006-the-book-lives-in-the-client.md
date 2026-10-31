# 0006 — The book lives in the client: an embedded store, journaled plays, chain-attested write-through

Date: 2026-10-31. Status: decided.

The day book's state of record in the browser is an **embedded
NEDB store** — the `nedb-wasm` build of the same engine that runs
server-side as `nedbd` (0005). One engine, both ends. The client
store is not a cache of the server and not a rendering aid; it is
where the desk's book actually lives while the desk works.

- **Reads — store first.** The book answers from the embedded
  store; the HTTP node reconciles behind it. A page load hydrates
  once from the preserved store (below); HTTP recovery is the
  fallback for a store that was never preserved, not the normal
  path.
- **Writes — plays, journaled, drained in bulk.** A gesture
  (book, move, status, price, note, checkout) records a *play* in
  the store first. Plays drain to the node in bulk on their own
  schedule; the node's confirmed state chains back into the
  store. No HTTP stands in the click path.
- **The journal is a DAG.** Plays carry explicit edges to the
  plays they depend on (a play on a booking depends on its
  birth). A play whose birth has not drained is held — per doc,
  so the rest of the book flows past it. A rejected play contests
  its doc: the queued tail holds, then replays onto the node's
  adopted base rather than being blindly resent.
- **Preservation.** Docs and journal are mirrored into IndexedDB
  as they are written and restored at boot, before the store is
  declared ready — a tab that dies mid-shift loses nothing it had
  journaled. The mirror keeps a working window (the newest plays
  inside 30 days); the node's store is the durable archive.
- **Chain attestation.** Every drain carries the client chain
  stamp `{seq, head}` sampled from the embedded engine with the
  batch's plays journaled. The server echoes the stamp on both
  apply endpoints; the client compares it exactly and preserves
  the last attested stamp. The write-through is therefore
  verifiable end to end against the same hash chain on both
  sides — the client journal and the server journal are one
  provenance story, not two logs that merely agree.
- **Paint before print.** A confirmed booking paints from the
  desk's own facts in the click's own frame — before the engine
  birth, before any network finalization. The store then births
  the doc under the very ref the paint already wears and adopts
  the standing block in place; the node's true entry replaces it
  at rename. Latency law: the desk never watches a spinner for a
  fact it already knows.
- **The roster book has the same shape** — its own embedded
  store and drain — and one availability resolver (perpetual
  pattern, overridden per date) is read by the day book, the
  roster book, and online booking alike.

Why, decided across 2026-10-30/31 while the pilot salon ran its
real book on this code:

- **The desk's machine is the hardware that matters.** Server
  round-trips on a real front-desk box made confirmed bookings
  take seconds to appear. The store-first shape takes the network
  and the server's query cost out of the gesture entirely.
- **Provenance without a second system.** Because the client
  store is NEDB itself, the desk's own plays are hash-chained at
  the moment they happen — the audit trail is a property of the
  store, per 0005's reasoning, extended to the edge.
- **Honest boundary, recorded so nobody overclaims it:** the
  render model is a plain-JavaScript projection fed by store
  events. The store is the state of record for the data; the
  view is not literally the store rendering itself. If that ever
  changes, it changes by a new record, not by quietly rewording
  this one.
