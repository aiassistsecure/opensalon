# Vendored nedb-wasm (client shadow store)

Prebuilt WebAssembly build of NEDB (https://github.com/aiassistsecure/nedb),
the same build the public NEDB Playground ships, vendored 2026-10-31 so the
day book's client shadow store needs no build step and no network beyond
this app's own static files.

- `nedb_wasm.js` — wasm-bindgen glue (ES module).
- `nedb_wasm_bg.wasm` — the engine, in-memory configuration in the browser.

The browser engine is in-memory only: the shadow store is a mirror of the
server's data (nedbd over HTTP remains the durable truth) and is rebuilt
from the client pack on every load. Durable browser storage (OPFS) is
upstream Phase 2 work in NEDB itself, not something this app fakes.
