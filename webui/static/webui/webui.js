/* OpenSalon webui behaviour: the day book's detail rail, tabs,
   team-chip column jumps, filter auto-submit — and the hot range.

   The hot range: the server remains the only renderer. On load
   the client caches the rendered day-book fragment for the shown
   date, then prefetches the rest of the week strip plus the
   neighbouring days. Switching days swaps a cached fragment in —
   no server round-trip stands between a tap and the paint — and
   falls back to a normal navigation whenever a fragment is not
   in hand. Every swap rebinds the book (rail, blocks, chips). */
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[c];
    });
  }

  var railEl = null;
  var railBody = null;
  var payloads = {};
  var selected = null;

  function pill(d) {
    return '<span class="pill pill-' + esc(d.status) + '">' + esc(d.status_label) + "</span>";
  }

  /* The card's price is a control, not a label: click it and
     it becomes an editor. An edited price carries the marker
     so the desk can see the card spoke, not the book. */
  function priceBtn(apptId, raw, label, overridden) {
    return '<button type="button" class="price-edit' + (overridden ? " overridden" : "") +
      '" data-price-edit data-appt="' + esc(apptId) + '" data-price="' + esc(raw || "") +
      '" title="Edit price' + (overridden ? " — edited from the book price" : "") +
      '">' + esc(label || "—") + (overridden ? ' <span class="price-dot" aria-hidden="true">•</span>' : "") + "</button>";
  }

  function noteBox(n, scope, apptId) {
    return '<div class="note-box"><span class="note-body">' + esc(n.body) + "</span>" +
      '<button type="button" class="note-edit" data-note-edit data-scope="' + scope +
      '" data-note-id="' + esc(n.id) + '" data-appt="' + esc(apptId) + '">Edit</button></div>';
  }

  function renderRail(d) {
    if (!railBody || !d) return;
    var contact = [d.client_email, d.client_phone].filter(Boolean).map(esc).join(" · ");
    var stack = d.stack.map(function (item) {
      return '<div class="stack-row' + (item.current ? " current" : "") + '">' +
        '<span class="stack-dot"></span>' +
        '<span class="stack-name">' + esc(item.service) + "</span>" +
        '<span class="stack-dur">' + esc(item.duration_label) + "</span>" +
        '<span class="stack-price">' + priceBtn(item.id, item.price, item.price_label, item.price_overridden) + "</span></div>";
    }).join("");
    var history = d.history.length ? d.history.map(function (h) {
      return '<div class="hrow"><span class="hrow-date">' + esc(h.date_label) + " · " +
        esc(h.time_label) + '</span><span class="hrow-svc">' + esc(h.service) +
        '</span><span class="hrow-meta">' + esc(h.stylist) + " · " + esc(h.status_label) +
        "</span></div>";
    }).join("") : '<p class="rail-empty">No other appointments on file.</p>';
    var apptNotes = (d.appt_notes.length ? d.appt_notes.map(function (n) {
      return noteBox(n, "appt", d.id);
    }).join("") : '<p class="rail-empty">No appointment notes.</p>') +
      '<button type="button" class="note-add" data-note-add data-scope="appt" data-appt="' +
      esc(d.id) + '">+ Add note</button>';
    var clientNotes = (d.client_notes.length ? d.client_notes.map(function (n) {
      return noteBox(n, "client", d.id);
    }).join("") : '<p class="rail-empty">No client record notes.</p>') +
      '<button type="button" class="note-add" data-note-add data-scope="client" data-appt="' +
      esc(d.id) + '">+ Add note</button>';

    railBody.innerHTML =
      '<div class="rail-head"><div><div class="rail-time">' + esc(d.time_label) +
      '</div><div class="rail-date">' + esc(d.date_label) + "</div></div>" + pill(d) +
      '<button type="button" class="rail-close" id="railClose" aria-label="Close detail">✕</button></div>' +
      '<div class="rail-client"><div class="avatar-lg">' + esc(d.client_initials) + "</div>" +
      '<div class="rail-client-meta"><div class="rail-cname">' + esc(d.client_name) + "</div>" +
      (contact ? '<div class="rail-contact">' + contact + "</div>" : "") +
      '<div class="rail-meta">' + esc(d.client_visits) + " appointment" +
      (d.client_visits === 1 ? "" : "s") + " on file · SMS " + (d.client_sms ? "✓" : "—") +
      " · Email " + (d.client_email_opt ? "✓" : "—") + "</div></div></div>" +
      '<div class="rail-tabs" role="tablist">' +
      '<button type="button" class="rtab active" data-tab="appointment">Appointment</button>' +
      '<button type="button" class="rtab" data-tab="client">Client</button>' +
      '<button type="button" class="rtab" data-tab="history">History</button>' +
      '<button type="button" class="rtab" data-tab="notes">Notes</button></div>' +
      '<div class="rpanel" data-panel="appointment">' +
      '<div class="stack-head"><span>Service Stack</span><span class="stack-total">' +
      esc(d.stack_total_label) + "</span></div>" + stack +
      '<div class="drow"><span class="drow-k">Stylist</span><span class="drow-v">' +
      '<span class="avatar-sm">' + esc(d.stylist_initials) + "</span>" + esc(d.stylist_name) +
      (d.stylist_level ? " · " + esc(d.stylist_level) : "") + "</span></div>" +
      '<div class="drow"><span class="drow-k">Date &amp; Time</span><span class="drow-v">' +
      esc(d.date_label) + "<br>" + esc(d.time_label) + "</span></div>" +
      '<div class="drow"><span class="drow-k">Price</span><span class="drow-v">' +
      priceBtn(d.id, d.price, d.price_label, d.price_overridden) + "</span></div>" +
      '<div class="drow"><span class="drow-k">Status</span><span class="drow-v">' + pill(d) + "</span></div>" +
      '<div class="drow"><span class="drow-k">Location</span><span class="drow-v">' +
      esc(d.salon_name) + "</span></div></div>" +
      '<div class="rpanel hidden" data-panel="client">' +
      '<div class="drow"><span class="drow-k">Email</span><span class="drow-v">' + esc(d.client_email || "—") + "</span></div>" +
      '<div class="drow"><span class="drow-k">Phone</span><span class="drow-v">' + esc(d.client_phone || "—") + "</span></div>" +
      '<div class="drow"><span class="drow-k">SMS reminders</span><span class="drow-v">' + (d.client_sms ? "Opted in" : "Not opted in") + "</span></div>" +
      '<div class="drow"><span class="drow-k">Email reminders</span><span class="drow-v">' + (d.client_email_opt ? "Opted in" : "Not opted in") + "</span></div>" +
      '<div class="drow"><span class="drow-k">On file</span><span class="drow-v">' + esc(d.client_visits) +
      " appointment" + (d.client_visits === 1 ? "" : "s") + "</span></div></div>" +
      '<div class="rpanel hidden" data-panel="history">' + history + "</div>" +
      '<div class="rpanel hidden" data-panel="notes">' +
      '<div class="notes-k">This appointment</div>' + apptNotes +
      '<div class="notes-k">Client record</div>' + clientNotes + "</div>" +
      ((d.toggles && d.toggles.length)
        ? '<div class="rail-toggles">' + d.toggles.map(function (t) {
            return '<div class="rtoggle-row"><span class="rtoggle-label">' +
              esc(t.label) + '</span><button type="button" class="tswitch t-' +
              esc(t.key) + (t.on ? " on" : "") + '" role="switch" aria-checked="' +
              (t.on ? "true" : "false") + '"' + (t.enabled ? "" : " disabled") +
              ' data-status-action="' + esc(t.target) + '" data-appt="' +
              esc(d.id) + '" aria-label="Toggle ' + esc(t.label.toLowerCase()) +
              '" title="' + (t.on
                ? esc(t.label) + ' is on — flip to undo'
                : 'Flip to mark ' + esc(t.label.toLowerCase())) +
              '"></button></div>';
          }).join("") + "</div>"
        : "") +
      ((d.actions && d.actions.length)
        ? '<div class="rail-actions">' + d.actions.map(function (a) {
            return '<button type="button" class="' +
              (a.primary ? "btn-grad grow" : "btn-ghost") +
              '" data-status-action="' + esc(a.status) + '" data-appt="' +
              esc(d.id) + '">' + esc(a.label) + "</button>";
          }).join("") + "</div>" +
          '<p class="rail-hint">Drag to move · Arrow keys nudge 5 min, ←/→ switch stylist · Ctrl+Z undoes a move.</p>'
        : "");
    if (railEl) railEl.setAttribute("data-current", d.id);
  }

  function choose(block, openSheet) {
    if (selected) selected.classList.remove("sel");
    selected = block;
    if (block) {
      block.classList.add("sel");
      renderRail(payloads[block.dataset.appt]);
      if (openSheet && railEl && window.innerWidth <= 760) railEl.classList.add("open");
    }
  }

  /* ---- drag a visit to another chair or a new time ----
     Pointer-driven so mouse and touch behave the same. The tile
     lifts out of its column and follows the pointer; a ghost in
     the target column shows the snapped landing spot (5-minute
     increments, the visit's whole stack moving as one piece).
     On drop the move posts to the server and the day re-reads —
     the book never keeps a position the server did not save. */
  function bindDrag(onlyTile) {
    var tiles = onlyTile
      ? [onlyTile]
      : document.querySelectorAll(".db-column .appt-block");
    tiles.forEach(function (tile) {
      tile.addEventListener("pointerdown", function (event) {
        if (event.button !== undefined && event.button !== 0) return;
        /* From the first pixel: no native drag, no text
           selection, no page highlight following the gesture. */
        event.preventDefault();
        var grid = tile.closest(".gridwrap");
        var col = tile.closest(".db-column");
        var layout = tile.closest(".book-layout");
        if (!grid || !col || !layout) return;
        var startX = event.clientX, startY = event.clientY;
        var engaged = false, ghost = null;
        var tileRect = tile.getBoundingClientRect();
        var gridRect = grid.getBoundingClientRect();
        var grabDX = event.clientX - tileRect.left;
        var grabDY = event.clientY - tileRect.top;
        var winMin = 12 * 60, dayStartMin = 8 * 60;
        var startMin0 = parseInt(tile.dataset.startMin || "0", 10);
        var durMin = Math.max(5, Math.round(tileRect.height / gridRect.height * winMin));
        var originMember = col.dataset.member;
        var target = { member: originMember, startMin: startMin0 };
        var origTop = tile.style.top, origHeight = tile.style.height;

        function fmt(mins) {
          var h = Math.floor(mins / 60), m = mins % 60;
          var ap = h < 12 ? "AM" : "PM", h12 = h % 12 || 12;
          return m ? h12 + ":" + (m < 10 ? "0" : "") + m + " " + ap : h12 + " " + ap;
        }
        function engage() {
          engaged = true;
          /* The whole page locks selection for the gesture's
             life: nothing highlights, nothing reads as copied. */
          document.body.classList.add("os-dragging");
          tile.classList.add("dragging");
          tile.style.width = tileRect.width + "px";
          tile.style.height = tileRect.height + "px";
          tile.style.left = tileRect.left + "px";
          tile.style.top = tileRect.top + "px";
          document.body.appendChild(tile);
          ghost = document.createElement("div");
          ghost.className = "drop-ghost";
          ghost.innerHTML = '<span class="ghost-time"></span>';
          ghost.style.top = origTop;
          ghost.style.height = origHeight;
          col.appendChild(ghost);
          try { tile.setPointerCapture(event.pointerId); } catch (e) {}
        }
        function onMove(e) {
          if (!engaged) {
            if (Math.abs(e.clientX - startX) + Math.abs(e.clientY - startY) < 7) return;
            engage();
          }
          e.preventDefault();
          tile.style.left = (e.clientX - grabDX) + "px";
          tile.style.top = (e.clientY - grabDY) + "px";
          /* Column hit-testing is pure geometry — never
             elementFromPoint. Whatever layer sits at the pointer
             (an hour tick, the now-line, a sticky head, the ghost)
             cannot get in the way of finding the column under x. */
          var tcol = null;
          var allCols = grid.querySelectorAll(".db-column");
          for (var ci = 0; ci < allCols.length; ci++) {
            var cr = allCols[ci].getBoundingClientRect();
            if (e.clientX >= cr.left && e.clientX <= cr.right) {
              tcol = allCols[ci];
              break;
            }
          }
          if (tcol) {
            target.member = tcol.dataset.member;
            if (ghost.parentElement !== tcol) tcol.appendChild(ghost);
          }
          var mins = (e.clientY - grabDY - gridRect.top) / gridRect.height * winMin;
          var snapped = Math.round(mins / 5) * 5;
          snapped = Math.max(0, Math.min(snapped, winMin - durMin));
          target.startMin = snapped;
          ghost.style.top = (snapped / winMin * 100) + "%";
          ghost.querySelector(".ghost-time").textContent =
            fmt(dayStartMin + snapped) + " – " + fmt(dayStartMin + snapped + durMin) +
            (target.member !== originMember ? " · new stylist" : "");
          /* Live stacking: the lanes make room DURING the drag,
             not after it — the column re-lanes around the tile's
             hover position on the next animation frame. */
          if (!filtersActive) {
            var previewStart = dayStartMin + target.startMin;
            if (!dragPreview || dragPreview.staff_id !== parseInt(target.member, 10) ||
                dragPreview.start_min !== previewStart) {
              dragPreview = {
                id: parseInt(tile.dataset.appt, 10),
                staff_id: parseInt(target.member, 10),
                start_min: previewStart,
              };
              if (!previewRaf) {
                previewRaf = true;
                requestAnimationFrame(function () {
                  previewRaf = false;
                  repaintDay();
                });
              }
            }
          }
        }
        function finish(commit) {
          tile.removeEventListener("pointermove", onMove);
          tile.removeEventListener("pointerup", onUp);
          tile.removeEventListener("pointercancel", onCancel);
          tile.removeEventListener("lostpointercapture", onCancel);
          document.body.classList.remove("os-dragging");
          if (!engaged) return;
          if (ghost) ghost.remove();
          dragPreview = null;
          var changed = target.member !== originMember || target.startMin !== startMin0;
          if (commit && changed && !filtersActive) {
            /* Optimistic: the model moves first and the grid
               repaints from it in this same frame; the write
               shadow-follows. The tile stays alive — repaint
               seats it in its new column. */
            var movedId = parseInt(tile.dataset.appt, 10);
            tile.classList.remove("dragging");
            if (applyMove(movedId, parseInt(target.member, 10), dayStartMin + target.startMin)) {
              queueShadow(movedId);
              return;
            }
          }
          /* The dragged element lives on <body> while it flies —
             on every non-optimistic path it must die here. A swap
             only replaces the layout; a body-level tile left
             behind is the stuck duplicate that haunted the first
             build. */
          tile.remove();
          if (commit && changed) {
            var tokenEl = layout.querySelector('input[name="csrfmiddlewaretoken"]');
            fetch(layout.dataset.move, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": tokenEl ? tokenEl.value : "",
              },
              body: JSON.stringify({
                appointment_id: parseInt(tile.dataset.appt, 10),
                staff_member_id: parseInt(target.member, 10),
                start_minutes: dayStartMin + target.startMin,
              }),
            }).then(function () { refreshDay(); }).catch(function () { refreshDay(); });
          } else {
            /* Cancelled or unmoved: the preview lanes snap back
               from the model instantly; the re-read converges. */
            repaintDay();
            refreshDay();
          }
        }
        function onUp() { finish(true); }
        function onCancel() { finish(false); }
        tile.addEventListener("pointermove", onMove);
        tile.addEventListener("pointerup", onUp);
        tile.addEventListener("pointercancel", onCancel);
        tile.addEventListener("lostpointercapture", onCancel);
      });
    });
  }

  var pendingReselect = null;

  function refreshDay(keepId) {
    pendingReselect = keepId || null;
    if (!currentDate || !fragmentBase) { window.location.reload(); return; }
    delete hotCache[currentDate];
    fetchFragment(currentDate).then(function () {
      swapTo(currentDate, false);
    }).catch(function () { window.location.reload(); });
  }

  function postStatus(apptId, status) {
    var layout = document.querySelector(".book-layout");
    if (!layout || !layout.dataset.status) return;
    if (window.OpenSalonShadow && window.OpenSalonShadow.ready) {
      /* Store first: the status flips in the embedded NEDB,
         the block and the switch repaint from it, the drain
         persists behind. Rail payloads re-read a beat later —
         a read, never a gate. */
      document.dispatchEvent(new CustomEvent("os:op", {
        detail: { kind: "status", id: parseInt(apptId, 10), status: status },
      }));
      repaintDay();
      var btn = railBody ? railBody.querySelector(
        '[data-status-action="' + status + '"][data-appt="' + apptId + '"]'
      ) : null;
      if (btn && btn.classList.contains("tswitch")) {
        btn.classList.toggle("on");
        btn.setAttribute(
          "aria-checked", btn.classList.contains("on") ? "true" : "false"
        );
      }
      /* The rail re-read waits for the drain's ack. Reading it
         now races the write: the fragment can land carrying the
         pre-write state and the card visibly un-flips the very
         toggle the desk just flipped. The ack is the first
         moment the server's word includes this play. */
      var onDrain = function () {
        document.removeEventListener("os:drain", onDrain);
        refreshRailData(apptId);
      };
      document.addEventListener("os:drain", onDrain);
      return;
    }
    var tokenEl = layout.querySelector('input[name="csrfmiddlewaretoken"]');
    fetch(layout.dataset.status, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": tokenEl ? tokenEl.value : "",
      },
      body: JSON.stringify({
        appointment_id: parseInt(apptId, 10),
        status: status,
      }),
    }).then(function () {
      /* The grid syncs in place from the pack; only the rail
         re-reads its payloads. No rebuild, no flicker. */
      pollPack();
      refreshRailData(apptId);
    }).catch(function () { refreshDay(apptId); });
  }

  /* ---- the card's editors: prices and notes ----
     Both write the way every play on this desk writes: store
     first when the embedded NEDB is live (journaled, queued,
     drained), the single-op endpoint when it is not. The card
     repaints from its payload at once; the server's re-read
     converges anything the local word got wrong. */

  function fmtPrice(v) {
    /* The server's label rule, mirrored: whole dollars whole. */
    if (v === "" || v == null || isNaN(parseFloat(v))) return "";
    var n = parseFloat(v);
    return n === Math.trunc(n) ? "$" + Math.trunc(n) : "$" + n.toFixed(2);
  }

  function renderRailKeepingTab(d) {
    var active = railBody
      ? railBody.querySelector(".rtab.active")
      : null;
    var tab = active ? active.dataset.tab : null;
    renderRail(d);
    if (tab && tab !== "appointment" && railBody) {
      railBody.querySelectorAll(".rtab").forEach(function (t) {
        t.classList.toggle("active", t.dataset.tab === tab);
      });
      railBody.querySelectorAll(".rpanel").forEach(function (p) {
        p.classList.toggle("hidden", p.dataset.panel !== tab);
      });
    }
  }

  function currentPayload() {
    return railEl ? payloads[railEl.getAttribute("data-current")] : null;
  }

  function postPrice(apptId, value) {
    var layout = document.querySelector(".book-layout");
    if (!layout) return;
    if (window.OpenSalonShadow && window.OpenSalonShadow.ready) {
      document.dispatchEvent(new CustomEvent("os:op", {
        detail: { kind: "price", id: parseInt(apptId, 10), price: value },
      }));
      return;
    }
    if (!layout.dataset.price) return;
    var tokenEl = layout.querySelector('input[name="csrfmiddlewaretoken"]');
    fetch(layout.dataset.price, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": tokenEl ? tokenEl.value : "",
      },
      body: JSON.stringify({ appointment_id: parseInt(apptId, 10), price: value }),
    }).then(function () {
      refreshRailData(apptId);
      pollPack();
    }).catch(function () { refreshRailData(apptId); });
  }

  function commitPrice(apptId, value) {
    var d = currentPayload();
    if (d) {
      var label = fmtPrice(value);
      d.stack.forEach(function (item) {
        if (String(item.id) === String(apptId)) {
          item.price = value;
          item.price_label = label;
          item.price_overridden = value !== "";
        }
      });
      if (String(d.id) === String(apptId)) {
        d.price = value;
        d.price_label = label;
        d.price_overridden = value !== "";
      }
      if (d.stack.every(function (i) { return i.price !== ""; })) {
        var total = d.stack.reduce(function (sum, i) {
          return sum + parseFloat(i.price || 0);
        }, 0);
        d.stack_price_label = fmtPrice(String(total));
      }
      renderRailKeepingTab(d);
    }
    postPrice(apptId, value);
  }

  function openPriceEditor(btn) {
    if (btn.dataset.editing) return;
    btn.dataset.editing = "1";
    var wrap = document.createElement("span");
    wrap.className = "price-editor";
    wrap.innerHTML =
      '<input class="price-input" type="text" inputmode="decimal" ' +
      'aria-label="Price" value="' + esc(btn.dataset.price || "") + '">' +
      '<span class="price-hint">Enter saves · empty clears to the book price</span>';
    btn.replaceWith(wrap);
    var input = wrap.querySelector(".price-input");
    input.focus();
    input.select();
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        commitPrice(btn.dataset.appt, input.value.trim());
      } else if (event.key === "Escape") {
        var d = currentPayload();
        if (d) renderRailKeepingTab(d);
      }
    });
    input.addEventListener("blur", function () {
      /* Blur commits — unless Escape already restored the card. */
      if (document.body.contains(wrap)) {
        commitPrice(btn.dataset.appt, input.value.trim());
      }
    });
  }

  function postNote(apptId, scope, noteId, body) {
    var layout = document.querySelector(".book-layout");
    if (!layout) return;
    if (window.OpenSalonShadow && window.OpenSalonShadow.ready) {
      document.dispatchEvent(new CustomEvent("os:op", {
        detail: {
          kind: "note", id: parseInt(apptId, 10), scope: scope,
          note_id: noteId, body: body,
        },
      }));
      /* The card re-reads once this drain acks — the note's
         real id and ordering are the server's word. */
      var onDrain = function () {
        document.removeEventListener("os:drain", onDrain);
        refreshRailData(apptId);
      };
      document.addEventListener("os:drain", onDrain);
      return;
    }
    if (!layout.dataset.note) return;
    var tokenEl = layout.querySelector('input[name="csrfmiddlewaretoken"]');
    fetch(layout.dataset.note, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": tokenEl ? tokenEl.value : "",
      },
      body: JSON.stringify({
        appointment_id: parseInt(apptId, 10), scope: scope,
        note_id: noteId, body: body,
      }),
    }).then(function () { refreshRailData(apptId); })
      .catch(function () { refreshRailData(apptId); });
  }

  function commitNote(scope, noteId, body, apptId) {
    var d = currentPayload();
    if (d) {
      var list = scope === "appt" ? d.appt_notes : d.client_notes;
      if (noteId != null) {
        list.forEach(function (n) {
          if (String(n.id) === String(noteId)) n.body = body;
        });
      } else {
        list.unshift({ id: 0, body: body });
      }
      renderRailKeepingTab(d);
    }
    postNote(apptId, scope, noteId, body);
  }

  function openNoteEditor(anchor, scope, noteId, apptId, currentBody) {
    if (railBody.querySelector(".note-editor")) return;
    var wrap = document.createElement("div");
    wrap.className = "note-editor";
    wrap.innerHTML =
      '<textarea class="note-input" rows="3" aria-label="Note">' +
      esc(currentBody || "") + "</textarea>" +
      '<div class="note-tools">' +
      '<button type="button" class="btn-grad" data-note-save>Save note</button>' +
      '<button type="button" class="btn-ghost" data-note-cancel>Cancel</button></div>';
    wrap.dataset.scope = scope;
    wrap.dataset.appt = apptId;
    if (noteId != null) wrap.dataset.noteId = noteId;
    anchor.closest(".note-box, .rpanel").appendChild(wrap);
    var input = wrap.querySelector(".note-input");
    input.focus();
  }

  /* Bind everything that lives inside the day-book layout. Runs
     on first load and again after every hot-range swap, because a
     swap replaces the layout node wholesale. */
  function bindBlock(block) {
    /* The card answers to deliberate acts only — a click, or
       Enter/Space on a focused block. Hover never opens it:
       the desk points at appointments all day without meaning
       to summon their cards. */
    block.addEventListener("click", function () { choose(block, true); });
    block.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        choose(block, true);
      }
    });
  }

  function bindBook() {
    sweepStrays();
    var shadowEl = document.getElementById("shadowState");
    if (shadowEl) {
      shadowEl.textContent =
        document.body.dataset.shadow === "live" ? "· Shadow journal live" : "";
    }
    railEl = document.getElementById("detailRail");
    railBody = document.getElementById("railBody");
    payloads = {};
    var dataEl = document.getElementById("rail-data");
    if (dataEl) {
      try { payloads = JSON.parse(dataEl.textContent); } catch (e) { payloads = {}; }
    }
    selected = null;

    document.querySelectorAll(".appt-block, .acard").forEach(bindBlock);

    bindDrag();

    // Mark the server-rendered default appointment as selected.
    if (railEl && railEl.getAttribute("data-current")) {
      var first = document.querySelector(
        '.appt-block[data-appt="' + railEl.getAttribute("data-current") + '"]'
      );
      if (first) { selected = first; first.classList.add("sel"); }
    }

    // After a write (a drag, a status change) the day re-reads;
    // keep the appointment the desk was working on selected.
    if (pendingReselect) {
      var keepId = pendingReselect;
      pendingReselect = null;
      var keep = document.querySelector(
        '.appt-block[data-appt="' + keepId + '"], .acard[data-appt="' + keepId + '"]'
      );
      if (keep && payloads[keepId]) choose(keep, false);
    }

    if (railBody) {
      railBody.addEventListener("click", function (event) {
        var priceBtnEl = event.target.closest("[data-price-edit]");
        if (priceBtnEl) { openPriceEditor(priceBtnEl); return; }
        var noteEdit = event.target.closest("[data-note-edit]");
        if (noteEdit) {
          var box = noteEdit.closest(".note-box");
          openNoteEditor(
            noteEdit, noteEdit.dataset.scope,
            noteEdit.dataset.noteId, noteEdit.dataset.appt,
            box ? box.querySelector(".note-body").textContent : ""
          );
          return;
        }
        var noteAdd = event.target.closest("[data-note-add]");
        if (noteAdd) {
          openNoteEditor(noteAdd, noteAdd.dataset.scope, null, noteAdd.dataset.appt, "");
          return;
        }
        var noteSave = event.target.closest("[data-note-save]");
        if (noteSave) {
          var editor = noteSave.closest(".note-editor");
          var body = editor.querySelector(".note-input").value.trim();
          if (!body) { editor.querySelector(".note-input").focus(); return; }
          commitNote(
            editor.dataset.scope,
            editor.dataset.noteId ? parseInt(editor.dataset.noteId, 10) : null,
            body, editor.dataset.appt
          );
          return;
        }
        if (event.target.closest("[data-note-cancel]")) {
          var d = currentPayload();
          if (d) renderRailKeepingTab(d);
          return;
        }
        var actionBtn = event.target.closest("[data-status-action]");
        if (actionBtn) {
          postStatus(actionBtn.dataset.appt, actionBtn.dataset.statusAction);
          return;
        }
        var tab = event.target.closest(".rtab");
        if (tab) {
          railBody.querySelectorAll(".rtab").forEach(function (t) {
            t.classList.toggle("active", t === tab);
          });
          railBody.querySelectorAll(".rpanel").forEach(function (p) {
            p.classList.toggle("hidden", p.dataset.panel !== tab.dataset.tab);
          });
          return;
        }
        if (event.target.closest("#railClose") && railEl) {
          railEl.classList.remove("open");
        }
      });
    }

    /* ---- team chips jump to a column (phone-first) ---- */
    var scroller = document.getElementById("bookscroll");
    document.querySelectorAll(".fchip").forEach(function (chip) {
      chip.addEventListener("click", function () {
        var col = document.getElementById("col-" + chip.dataset.col);
        if (!scroller || !col) return;
        var gutter = document.querySelector(".db-gutter");
        var offset = gutter ? gutter.offsetWidth : 0;
        var target = col.getBoundingClientRect().left -
          scroller.getBoundingClientRect().left + scroller.scrollLeft - offset;
        scroller.scrollTo({ left: Math.max(0, target), behavior: "smooth" });
      });
    });

    /* ---- filter selects apply immediately ---- */
    document.querySelectorAll(".filters select[name]").forEach(function (sel) {
      sel.addEventListener("change", function () { sel.form.submit(); });
    });
  }

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && railEl) railEl.classList.remove("open");
  });

  /* ================= the hot range ================= */
  var layoutEl = document.querySelector(".book-layout");
  var filtersActive = /[?&](cat|status)=[^&]/.test(window.location.search);
  var hotCache = {};
  var currentDate = null;
  var fragmentBase = null;

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function toISO(d) {
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }
  function addDays(iso, n) {
    var p = iso.split("-");
    var d = new Date(+p[0], +p[1] - 1, +p[2]);
    d.setDate(d.getDate() + n);
    return toISO(d);
  }
  var scheduleIdle = window.requestIdleCallback
    ? function (fn) { window.requestIdleCallback(fn, { timeout: 1200 }); }
    : function (fn) { window.setTimeout(fn, 350); };

  function fetchFragment(iso) {
    return fetch(fragmentBase + "?date=" + iso, {
      headers: { "X-Requested-With": "XMLHttpRequest" },
    }).then(function (r) {
      if (!r.ok) throw new Error("fragment " + r.status);
      return r.text();
    }).then(function (html) {
      hotCache[iso] = html;
      return html;
    });
  }

  function prefetchAround(iso) {
    var dates = [addDays(iso, -1), addDays(iso, 1)];
    document.querySelectorAll(".wpill").forEach(function (a) {
      var m = /date=(\d{4}-\d{2}-\d{2})/.exec(a.getAttribute("href") || "");
      if (m) dates.push(m[1]);
    });
    dates.forEach(function (d) {
      if (!hotCache[d]) {
        scheduleIdle(function () {
          if (!hotCache[d]) fetchFragment(d).catch(function () {});
        });
      }
    });
  }

  function sweepStrays() {
    /* A dragged tile rides on <body> while it flies; if anything
       interrupted a drag, its tile can outlive the layout it came
       from. Any body-level appointment block is an orphan. */
    document.querySelectorAll("body > .appt-block").forEach(function (el) {
      el.remove();
    });
  }

  function swapTo(iso, push) {
    var html = hotCache[iso];
    if (!html || !layoutEl) { window.location.href = "?date=" + iso; return; }
    sweepStrays();
    var wrap = document.createElement("div");
    wrap.innerHTML = html;
    var fresh = wrap.querySelector(".book-layout");
    if (!fresh) { window.location.href = "?date=" + iso; return; }
    fresh.classList.add("synced");
    layoutEl.replaceWith(fresh);
    layoutEl = fresh;
    currentDate = iso;
    bindBook();
    pollPack();
    var title = fresh.querySelector(".day-title");
    var sub = fresh.querySelector(".day-sub");
    if (title && sub) {
      document.title = "Daybook — " + title.textContent.trim() + ", " +
        sub.textContent.trim() + " · OpenSalon";
    }
    if (push) history.pushState({ date: iso }, "", "?date=" + iso);
    prefetchAround(iso);
  }

  function goTo(iso, push) {
    if (hotCache[iso]) { swapTo(iso, push); return; }
    fetchFragment(iso).then(function () { swapTo(iso, push); }).catch(function () {
      window.location.href = "?date=" + iso;
    });
  }

  if (layoutEl && layoutEl.dataset.date && layoutEl.dataset.fragment && !filtersActive) {
    currentDate = layoutEl.dataset.date;
    fragmentBase = layoutEl.dataset.fragment;
    hotCache[currentDate] = layoutEl.outerHTML;
    history.replaceState({ date: currentDate }, "", window.location.href);

    document.addEventListener("click", function (event) {
      var a = event.target.closest('a[href*="?date="]');
      if (!a) return;
      var m = /date=(\d{4}-\d{2}-\d{2})/.exec(a.getAttribute("href") || "");
      if (!m) return;
      event.preventDefault();
      if (m[1] !== currentDate) goTo(m[1], true);
    });

    window.addEventListener("popstate", function () {
      var m = /date=(\d{4}-\d{2}-\d{2})/.exec(window.location.search);
      var iso = m ? m[1] : currentDate;
      if (iso && iso !== currentDate) goTo(iso, false);
    });

    prefetchAround(currentDate);
  }

  /* ---- the live model + optimistic repaint ----
     The pack's data, held as the client's own model of the week.
     A gesture (drag, arrow keys) mutates the model first and
     repaints from it in the same frame — lanes resize the instant
     a block crosses columns, no server round-trip in the hand's
     way. The write itself shadow-follows: one POST per gesture
     (debounced through a key burst), then the day reconciles
     from the server fragment as always. If the model cannot
     answer (filtered view, day not packed), the gesture falls
     back to the plain server path. */
  var model = { days: {}, staff: [], anchor: null, anchorDate: "" };
  var filtersActive = /[?&](cat|status)=[^&]/.test(window.location.search);
  var dragPreview = null;
  var previewRaf = false;
  var lastAgendaSig = "";

  function buildModel(pack, forDate) {
    if (pack && pack.days) {
      model = {
        days: pack.days,
        staff: pack.staff || [],
        anchor: pack.anchor || null,
        anchorDate: pack.anchor ? (forDate || currentDate) : "",
      };
      /* Feed the shadow store (embedded NEDB) the same pack. */
      document.dispatchEvent(new CustomEvent("os:pack", { detail: pack }));
    }
  }
  function modelDay() {
    return (model.days && model.days[currentDate]) || null;
  }
  function fmtClock(mins) {
    var h = Math.floor(mins / 60), m = mins % 60;
    var ap = h < 12 ? "AM" : "PM", h12 = h % 12 || 12;
    return m ? h12 + ":" + (m < 10 ? "0" : "") + m + " " + ap : h12 + " " + ap;
  }

  function lanesFor(entries) {
    var sorted = entries.slice().sort(function (a, b) {
      return a.start_min - b.start_min || a.id - b.id;
    });
    var result = {}, clusters = [], current = [], currentEnd = null;
    sorted.forEach(function (e) {
      if (current.length && e.start_min >= currentEnd) {
        clusters.push(current); current = []; currentEnd = null;
      }
      current.push(e);
      currentEnd = Math.max(currentEnd === null ? e.end_min : currentEnd, e.end_min);
    });
    if (current.length) clusters.push(current);
    clusters.forEach(function (cluster) {
      var laneEnds = [];
      cluster.forEach(function (e) {
        var lane = -1;
        for (var i = 0; i < laneEnds.length; i++) {
          if (e.start_min >= laneEnds[i]) { laneEnds[i] = e.end_min; lane = i; break; }
        }
        if (lane === -1) { laneEnds.push(e.end_min); lane = laneEnds.length - 1; }
        e._lane = lane;
      });
      var lanes = laneEnds.length, width = 100 / lanes;
      cluster.forEach(function (e) {
        var probes = [e.start_min];
        cluster.forEach(function (b) {
          if (e.start_min < b.start_min && b.start_min < e.end_min) probes.push(b.start_min);
        });
        var overlap = 0;
        probes.forEach(function (t) {
          var n = 0;
          cluster.forEach(function (b) { if (b.start_min <= t && t < b.end_min) n++; });
          overlap = Math.max(overlap, n);
        });
        result[e.id] = {
          left: Math.round(e._lane * width * 100) / 100,
          width: Math.round(width * 100) / 100,
          overlap: overlap,
        };
      });
    });
    return result;
  }

  function paintBlock(el, entry, info) {
    el.style.top = ((entry.start_min - 480) / 720 * 100) + "%";
    el.style.height = Math.max((entry.end_min - entry.start_min) / 720 * 100, 4.0) + "%";
    if (info) {
      el.style.left = "calc(" + info.left + "% + 5px)";
      el.style.width = "calc(" + info.width + "% - 10px)";
    }
    el.dataset.startMin = String(entry.start_min - 480);
    var dur = entry.end_min - entry.start_min;
    el.classList.toggle("mini", dur < 45 || (info && info.overlap >= 3 && dur < 90));
    el.classList.toggle("micro", dur < 30);
    if (el.dataset.cat !== entry.cat) {
      if (el.dataset.cat) el.classList.remove("cat-" + el.dataset.cat);
      el.classList.add("cat-" + entry.cat);
      el.dataset.cat = entry.cat;
    }
    if (el.dataset.status !== entry.status) {
      if (el.dataset.status) el.classList.remove("status-" + el.dataset.status);
      el.classList.add("status-" + entry.status);
      el.dataset.status = entry.status;
    }
    var timeLabel = entry.time_label ||
      (fmtClock(entry.start_min) + " – " + fmtClock(entry.end_min));
    var timeEl = el.querySelector(".b-time");
    if (timeEl) timeEl.textContent = timeLabel;
    var clientEl = el.querySelector(".b-client");
    if (clientEl) clientEl.textContent = entry.client;
    var svcEl = el.querySelector(".b-service");
    if (svcEl) svcEl.textContent = entry.service;
    var priceEl = el.querySelector(".b-price");
    if (entry.price_label) {
      if (!priceEl) {
        priceEl = document.createElement("div");
        priceEl.className = "b-price";
        el.appendChild(priceEl);
      }
      priceEl.textContent = entry.price_label;
    } else if (priceEl) {
      priceEl.remove();
    }
    el.setAttribute("aria-label", entry.client + ", " + entry.service + ", " + timeLabel);
    el.title = entry.client + " · " + entry.service + " · " + timeLabel;
  }

  /* A block built on the client, indistinguishable from the
     server's _block.html — the factory that lets the grid absorb
     a new appointment without rebuilding the page. */
  function renderBlock(entry) {
    var el = document.createElement("article");
    el.className = "appt-block cat-" + entry.cat + " status-" + entry.status;
    el.setAttribute("tabindex", "0");
    el.setAttribute("role", "button");
    el.dataset.appt = String(entry.id);
    el.dataset.cat = entry.cat;
    el.dataset.status = entry.status;
    el.innerHTML =
      '<div class="b-top"><span class="b-time"></span>' +
      '<span class="b-ico" aria-hidden="true"></span></div>' +
      '<div class="b-client"></div>' +
      '<div class="b-services"><div class="b-service"></div></div>';
    bindBlock(el);
    bindDrag(el);
    return el;
  }

  function effectiveEntries() {
    var entries = modelDay();
    if (!entries || !dragPreview) return entries;
    return entries.map(function (e) {
      if (e.id !== dragPreview.id) return e;
      var dur = e.end_min - e.start_min;
      return Object.assign({}, e, {
        staff_id: dragPreview.staff_id,
        start_min: dragPreview.start_min,
        end_min: dragPreview.start_min + dur,
      });
    });
  }

  function repaintDay() {
    var entries = effectiveEntries();
    if (!entries || !layoutEl) return false;
    var byStaff = {};
    entries.forEach(function (e) {
      (byStaff[e.staff_id] = byStaff[e.staff_id] || []).push(e);
    });
    var factors = [];
    layoutEl.querySelectorAll(".db-column").forEach(function (col) {
      var list = byStaff[col.dataset.member] || [];
      var lanes = lanesFor(list);
      var maxOverlap = 1;
      list.forEach(function (e) {
        var info = lanes[e.id];
        if (info) maxOverlap = Math.max(maxOverlap, info.overlap);
        var el = document.querySelector('.appt-block[data-appt="' + e.id + '"]');
        if (!el || el.classList.contains("dragging")) return;
        if (el.parentElement !== col) col.appendChild(el);
        paintBlock(el, e, info);
      });
      factors.push(Math.min(3, maxOverlap));
    });
    var tracks = "var(--gutter) " + factors.map(function (f) {
      return "minmax(calc(var(--colunit) * " + f + "), " + f + "fr)";
    }).join(" ");
    /* Column widths freeze while a drag is in flight: lanes
       re-flow inside the columns, but the columns themselves
       hold still — nothing slides or hides mid-gesture, and the
       pointer math the drag started with stays true. Widths
       settle on drop, when the lock lifts. */
    if (!document.body.classList.contains("os-dragging")) {
      layoutEl.querySelectorAll(".colheads, .gridwrap").forEach(function (el) {
        el.style.setProperty("--tracks", tracks);
      });
    }
    return true;
  }

  /* ---- in-place reconcile: the sturdy composition ----
     The grid absorbs the model's truth by mutating what exists:
     blocks are created, seated, repainted, or removed — the
     layout itself is never torn down, scroll and selection
     survive, and nothing re-animates. A structural change the
     model cannot express (a stylist column appears or vanishes)
     returns false and the caller takes one honest rebuild. */
  function syncFromModel() {
    if (!layoutEl || filtersActive) return false;
    var entries = modelDay();
    if (!entries) return false;
    var anchor = model.anchorDate === currentDate ? model.anchor : null;
    if (anchor && anchor.columns) {
      var domMembers = Array.prototype.map.call(
        layoutEl.querySelectorAll(".db-column"),
        function (c) { return c.dataset.member; }
      );
      var want = anchor.columns.map(function (c) { return String(c.member); });
      if (domMembers.join(",") !== want.join(",")) return false;
    }
    var byStaff = {};
    entries.forEach(function (e) {
      (byStaff[e.staff_id] = byStaff[e.staff_id] || []).push(e);
    });
    layoutEl.querySelectorAll(".db-column").forEach(function (col) {
      var list = byStaff[col.dataset.member] || [];
      var wantIds = {};
      list.forEach(function (e) { wantIds[e.id] = true; });
      col.querySelectorAll(".appt-block").forEach(function (el) {
        if (!wantIds[el.dataset.appt]) el.remove();
      });
      list.forEach(function (e) {
        if (!document.querySelector('.appt-block[data-appt="' + e.id + '"]')) {
          var fresh = renderBlock(e);
          fresh.classList.add("fresh");
          col.appendChild(fresh);
          setTimeout(function () { fresh.classList.remove("fresh"); }, 1500);
        }
      });
      var openLabel = col.querySelector(".open-label");
      if (list.length && openLabel) openLabel.remove();
      if (!list.length && !openLabel && !col.classList.contains("offduty")) {
        var label = document.createElement("div");
        label.className = "open-label";
        label.textContent = "Open for bookings";
        col.appendChild(label);
      }
    });
    repaintDay();
    if (anchor) {
      updateRibbon(anchor);
      updateIntel(anchor);
      updateColheads(anchor);
      updateAgenda(anchor);
    }
    if (selected && !document.querySelector(
      '.appt-block[data-appt="' + selected.dataset.appt + '"]'
    )) {
      selected = null;
    }
    return true;
  }

  function setText(scope, selector, value) {
    var el = scope.querySelector(selector);
    if (el) el.textContent = value;
  }

  function updateRibbon(anchor) {
    var kpis = layoutEl.querySelectorAll(".kpis .kpi");
    var r = anchor.ribbon;
    if (kpis[0]) {
      setText(kpis[0], ".kpi-v", r.revenue_label);
      setText(kpis[0], ".kpi-s", r.unpriced ? r.unpriced + " unpriced" : "All priced");
    }
    if (kpis[1]) {
      setText(kpis[1], ".kpi-v", String(r.appointments));
      setText(kpis[1], ".kpi-s", r.visits + (r.visits === 1 ? " visit" : " visits"));
    }
    if (kpis[2]) {
      setText(kpis[2], ".kpi-v", r.utilization != null ? r.utilization + "%" : "—");
    }
    if (kpis[3]) setText(kpis[3], ".kpi-v", r.avg_ticket_label);
    if (kpis[4]) setText(kpis[4], ".kpi-v", String(r.new_clients));
  }

  function updateIntel(anchor) {
    var stats = layoutEl.querySelectorAll(".intel-stats .istat-v");
    if (stats[0]) stats[0].textContent = String(anchor.ribbon.appointments);
    if (stats[1]) stats[1].textContent = String(anchor.intel.completed);
    if (stats[2]) stats[2].textContent = String(anchor.intel.remaining);
    if (stats[3]) stats[3].textContent = anchor.intel.top_label;
    setText(layoutEl, ".nba-title", "Next Opening — " + anchor.intel.next_label);
    setText(layoutEl, ".nba-sub", anchor.intel.next_sub);
  }

  function updateColheads(anchor) {
    var heads = layoutEl.querySelectorAll(".colhead:not(.colcorner)");
    anchor.columns.forEach(function (col, i) {
      var head = heads[i];
      if (!head) return;
      var level = "";
      model.staff.forEach(function (s) { if (s.id === col.member) level = s.level; });
      setText(head, ".cutil",
        (level ? level + " · " : "") + col.day_total_label + " · " +
        col.visits_count + (col.visits_count === 1 ? " visit" : " visits"));
    });
  }

  function updateAgenda(anchor) {
    var section = layoutEl.querySelector(".agenda");
    if (!section || !anchor.agenda) return;
    var sig = anchor.agenda.map(function (a) {
      return a.appointment_id + ":" + a.time_label + ":" + a.total_label;
    }).join("|") + "#" + anchor.agenda_now_index;
    if (sig === lastAgendaSig) return;
    lastAgendaSig = sig;
    section.textContent = "";
    anchor.agenda.forEach(function (item, i) {
      if (anchor.agenda_now_index === i) {
        var now = document.createElement("div");
        now.className = "agenda-now";
        var span = document.createElement("span");
        span.textContent = "Now · " + anchor.now_label;
        now.appendChild(span);
        section.appendChild(now);
      }
      var card = document.createElement("article");
      card.className = "acard";
      card.dataset.appt = String(item.appointment_id);
      card.setAttribute("tabindex", "0");
      card.setAttribute("role", "button");
      card.setAttribute("aria-label",
        item.client_name + ", " + item.services_label + ", " + item.time_label);
      var t = document.createElement("div");
      t.className = "acard-t";
      t.textContent = item.time_label;
      var b = document.createElement("div");
      b.className = "acard-b";
      var c = document.createElement("div");
      c.className = "acard-c";
      var name = document.createElement("span");
      name.textContent = item.client_name;
      c.appendChild(name);
      if (item.total_label) {
        var total = document.createElement("b");
        total.textContent = item.total_label;
        c.appendChild(total);
      }
      var s = document.createElement("div");
      s.className = "acard-s";
      s.textContent = item.services_label;
      var st = document.createElement("div");
      st.className = "acard-st";
      var dot = document.createElement("span");
      dot.className = "adot av-" + item.staff_index;
      dot.setAttribute("aria-hidden", "true");
      st.appendChild(dot);
      st.appendChild(document.createTextNode(item.staff_name));
      b.appendChild(c); b.appendChild(s); b.appendChild(st);
      card.appendChild(t); card.appendChild(b);
      bindBlock(card);
      section.appendChild(card);
    });
    if (!anchor.agenda.length) {
      var empty = document.createElement("div");
      empty.className = "empty-card";
      empty.innerHTML = '<div class="empty-title">No appointments on the book</div>' +
        '<p class="empty-sub">Nothing is booked for this day.</p>';
      section.appendChild(empty);
    }
  }

  /* Rail data without a page rebuild: the fragment is fetched
     only for its rail payloads; the grid never sees it. */
  function refreshRailData(keepId) {
    if (!layoutEl) return;
    fetch(layoutEl.dataset.fragment + "?date=" + encodeURIComponent(currentDate), {
      headers: { "X-Requested-With": "fetch" },
    })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, "text/html");
        var dataEl = doc.getElementById("rail-data");
        if (dataEl) {
          try { payloads = JSON.parse(dataEl.textContent); } catch (e) { /* keep old */ }
        }
        if (keepId && payloads[keepId]) {
          renderRail(payloads[keepId]);
          var keep = document.querySelector(
            '.appt-block[data-appt="' + keepId + '"]'
          );
          if (keep) {
            if (selected) selected.classList.remove("sel");
            selected = keep;
            keep.classList.add("sel");
          }
        }
      })
      .catch(function () {});
  }

  function applyMove(id, staffId, startMin, via) {
    var entries = modelDay();
    if (!entries) return false;
    var found = null;
    entries.forEach(function (e) { if (e.id === id) found = e; });
    if (!found) return false;
    var before = { staff_id: found.staff_id, start_min: found.start_min };
    var dur = found.end_min - found.start_min;
    /* The founder's order of operations: the play records in
       the embedded store FIRST (its os:record syncs this very
       entry, synchronously), the repaint reads the store's
       truth, and persistence drains behind. Only when the
       engine is down does the projection move on its own and
       the legacy shadow-write carry the save. */
    var storeDriven = !!(window.OpenSalonShadow && window.OpenSalonShadow.ready);
    if (!storeDriven) {
      found.staff_id = staffId;
      found.start_min = startMin;
      found.end_min = startMin + dur;
    }
    document.dispatchEvent(new CustomEvent("os:op", {
      detail: {
        kind: "move", id: id, via: via || "",
        before: before, after: { staff_id: staffId, start_min: startMin },
      },
    }));
    return repaintDay();
  }

  /* The store's word on a record is the projection's word:
     when the embedded NEDB applies a play, its doc lands here
     and the render model follows it — one writer, one truth. */
  document.addEventListener("os:record", function (event) {
    var doc = event.detail;
    if (!doc || doc.day !== currentDate) return;
    var entries = modelDay();
    if (!entries) return;
    entries.forEach(function (e) {
      if (e.id === doc.id) {
        e.staff_id = doc.staff_id;
        e.start_min = doc.start_min;
        e.end_min = doc.end_min;
        e.status = doc.status;
        e.amount = doc.amount;
        e.price_label = doc.price_label;
      }
    });
  });

  /* A rejected op means the server's book disagrees with a
     play the desk already saw — converge on the truth. */
  document.addEventListener("os:drain", function (event) {
    var failed = (event.detail && event.detail.failed) || [];
    if (failed.length) {
      refreshDay(selected ? selected.dataset.appt : null);
    } else {
      /* Acked: re-stamp against the server so the mirror and
         the book agree — the sync it triggers is invisible,
         because the geometry already matches. */
      pollPack();
    }
  });

  /* Undo: the shadow journal still holds the move's before
     state — Ctrl+Z asks it for the restore and applies it like
     any other move (which journals the undo as its own op). */
  document.addEventListener("os:undo-move", function (event) {
    var d = event.detail || {};
    if (applyMove(d.id, d.staff_id, d.start_min, "undo")) queueShadow(d.id);
  });

  /* A booking made from the modal while the day book is open
     lands in place: the pack sync creates the block (with the
     fresh pulse), the rail loads its payload — no page load. */
  document.addEventListener("os:booked", function (event) {
    var d = event.detail || {};
    if (!layoutEl || d.date !== currentDate) return;
    d.handled = true;
    pollPack();
    setTimeout(function () { refreshRailData(d.id); }, 350);
  });

  var shadowPending = {};
  var shadowTimer = null;
  function queueShadow(id) {
    /* Store-driven plays already sit in the embedded outbox;
       the drainer owns their persistence. */
    if (window.OpenSalonShadow && window.OpenSalonShadow.ready) return;
    var entries = modelDay();
    if (!entries) return;
    entries.forEach(function (e) {
      if (e.id === id) {
        shadowPending[id] = { staff_member_id: e.staff_id, start_minutes: e.start_min };
      }
    });
    if (shadowTimer) clearTimeout(shadowTimer);
    shadowTimer = setTimeout(flushShadow, 320);
  }
  function flushShadow() {
    if (!layoutEl || !layoutEl.dataset.move) return;
    var tokenEl = layoutEl.querySelector('input[name="csrfmiddlewaretoken"]');
    var ids = Object.keys(shadowPending);
    var jobs = ids.map(function (id) {
      var body = shadowPending[id];
      return fetch(layoutEl.dataset.move, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": tokenEl ? tokenEl.value : "",
        },
        body: JSON.stringify({
          appointment_id: parseInt(id, 10),
          staff_member_id: body.staff_member_id,
          start_minutes: body.start_minutes,
        }),
      }).catch(function () {});
    });
    shadowPending = {};
    Promise.all(jobs).then(function (responses) {
      /* Reconcile by pack sync, never by rebuilding the page:
         the geometry already matches, so the sync is invisible.
         A failed write is the one case that earns a rebuild —
         the screen must not keep a position the server refused. */
      var failed = responses.some(function (r) { return !r || !r.ok; });
      if (failed) {
        refreshDay(ids.length ? parseInt(ids[ids.length - 1], 10) : null);
      } else if (ids.length && !document.querySelector(".appt-block.dragging")) {
        pollPack();
      }
    });
  }

  document.addEventListener("keydown", function (event) {
    if ((event.ctrlKey || event.metaKey) && !event.shiftKey &&
        (event.key === "z" || event.key === "Z")) {
      if (event.target.closest("input, textarea, select")) return;
      event.preventDefault();
      document.dispatchEvent(new CustomEvent("os:undo"));
    }
  });

  /* Arrow keys drive the selected block: up/down in 5-minute
     steps, left/right across stylists — reacting on keydown,
     auto-repeat included, one shadow-write per burst. */
  document.addEventListener("keydown", function (event) {
    if (!layoutEl || filtersActive) return;
    if (document.querySelector(".book-modal:not(.hidden)")) return;
    if (event.target.closest("input, textarea, select, .book-modal")) return;
    if (!selected || !selected.classList.contains("appt-block")) return;
    var id = parseInt(selected.dataset.appt, 10);
    var entries = modelDay();
    if (!entries) return;
    var entry = null;
    entries.forEach(function (e) { if (e.id === id) entry = e; });
    if (!entry) return;
    var dur = entry.end_min - entry.start_min;
    var staffId = entry.staff_id, startMin = entry.start_min;
    if (event.key === "ArrowDown") startMin = Math.min(startMin + 5, 1200 - dur);
    else if (event.key === "ArrowUp") startMin = Math.max(startMin - 5, 480);
    else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      var cols = Array.prototype.map.call(
        layoutEl.querySelectorAll(".db-column"),
        function (c) { return parseInt(c.dataset.member, 10); }
      );
      var idx = cols.indexOf(staffId);
      var next = event.key === "ArrowLeft" ? idx - 1 : idx + 1;
      if (next < 0 || next >= cols.length) return;
      staffId = cols[next];
    } else return;
    event.preventDefault();
    if (applyMove(id, staffId, startMin)) queueShadow(id);
  });

  /* ---- freshness poll ----
     The book is shared: another desk's booking, a check-in from
     the rail down the hall, an online reservation — an open
     screen must learn about them without being asked. The
     client polls the pack's version stamp (a one-line answer
     when nothing changed) and re-reads the day only when the
     world actually moved. Polling pauses while a drag is in
     hand: the hand outranks the mirror. */
  var packVersion = null;
  var pollBusy = false;
  document.addEventListener("os:shadow-ready", function () {
    var shadowEl = document.getElementById("shadowState");
    if (shadowEl) shadowEl.textContent = "· Shadow journal live";
    /* The engine may boot after the first pack was dispatched;
       re-feed it so the mirror is seeded either way. */
    if (model.days && Object.keys(model.days).length) {
      document.dispatchEvent(
        new CustomEvent("os:pack", { detail: { days: model.days, version: packVersion || "reseeding" } })
      );
    }
  });

  function pollPack() {
    if (pollBusy || document.hidden) return;
    if (document.querySelector(".appt-block.dragging")) return;
    pollBusy = true;
    /* A switched day needs a fresh anchor even when the week's
       version stands — the anchor extras describe one day only. */
    var staleAnchor = model.anchorDate !== currentDate;
    var url = "/daybook/pack/?date=" + encodeURIComponent(currentDate || "") +
      (packVersion && !staleAnchor
        ? "&stamp=" + encodeURIComponent(packVersion)
        : "");
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.version) return;
        var initial = packVersion === null;
        var moved = data.changed && data.version !== packVersion;
        packVersion = data.version;
        if (!data.days) return;
        buildModel(data, currentDate);
        if (!initial && !moved && !staleAnchor) return;
        /* Our own writes still in flight (the legacy shadow
           queue, or the embedded store's undrained outbox):
           syncing now would repaint from a server state that
           has not seen them yet. The drain ack re-polls. */
        var storePending = window.OpenSalonShadow && window.OpenSalonShadow.ready &&
          window.OpenSalonShadow.pending();
        if (Object.keys(shadowPending).length || shadowTimer || storePending) return;
        if (!syncFromModel() && !initial) {
          refreshDay(railEl ? railEl.getAttribute("data-current") : null);
        }
      })
      .catch(function () {})
      .finally(function () { pollBusy = false; });
  }
  if (layoutEl) {
    pollPack();
    setInterval(pollPack, 25000);
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) pollPack();
    });
  }

  bindBook();
})();

/* ---------- collapsible sidebar (every page) ---------- */
(function () {
  var KEY = "os-side-collapsed";
  try {
    if (localStorage.getItem(KEY) === "1") {
      document.body.classList.add("side-collapsed");
    }
  } catch (e) {}
  var btn = document.getElementById("sideToggle");
  if (!btn) return;
  function sync() {
    var collapsed = document.body.classList.contains("side-collapsed");
    btn.textContent = collapsed ? "»" : "«";
    btn.title = collapsed ? "Expand sidebar" : "Collapse sidebar";
    btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
  }
  btn.addEventListener("click", function () {
    var collapsed = document.body.classList.toggle("side-collapsed");
    try { localStorage.setItem(KEY, collapsed ? "1" : "0"); } catch (e) {}
    sync();
  });
  sync();
})();

/* ---------- new appointment (every page) ---------- */
(function () {
  var modal = document.getElementById("bookModal");
  var openBtn = document.getElementById("newApptBtn");
  if (!modal || !openBtn) return;
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  var pickedClient = null;
  var optionsLoaded = false;
  var searchTimer = null;

  function show() {
    modal.classList.remove("hidden");
    if (!optionsLoaded) loadOptions();
    $("bkSearch").focus();
  }
  function hide() { modal.classList.add("hidden"); }

  function loadOptions() {
    fetch("/daybook/book/options/")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        optionsLoaded = true;
        $("bkMember").innerHTML = data.members.map(function (m) {
          return '<option value="' + m.id + '">' + esc(m.name) + "</option>";
        }).join("");
        $("bkService").innerHTML = data.services.map(function (s) {
          return '<option value="' + s.id + '">' + esc(s.name) +
            (s.minutes ? " · " + s.minutes + "m" : "") + "</option>";
        }).join("");
        if (data.today && !$("bkDate").value) $("bkDate").value = data.today;
      })
      .catch(function () {});
  }

  function setPicked(client) {
    pickedClient = client;
    var box = $("bkPicked");
    if (client) {
      box.innerHTML = "<span>" + esc(client.name) +
        (client.phone ? " · " + esc(client.phone) : "") +
        '</span><button type="button" id="bkUnpick" aria-label="Clear client">✕</button>';
      box.classList.remove("hidden");
      $("bkResults").classList.add("hidden");
      $("bkNew").classList.add("hidden");
      $("bkUnpick").addEventListener("click", function () { setPicked(null); });
    } else {
      box.classList.add("hidden");
      box.innerHTML = "";
    }
  }

  $("bkSearch").addEventListener("input", function () {
    var q = $("bkSearch").value.trim();
    setPicked(null);
    if (searchTimer) clearTimeout(searchTimer);
    if (q.length < 2) { $("bkResults").classList.add("hidden"); return; }
    searchTimer = setTimeout(function () {
      fetch("/daybook/clients/search/?q=" + encodeURIComponent(q))
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var box = $("bkResults");
          if (!data.clients.length) {
            box.innerHTML = '<p class="book-noresults">No match — add them as a new client below.</p>';
          } else {
            box.innerHTML = data.clients.map(function (c) {
              return '<button type="button" class="book-result" data-id="' + c.id +
                '" data-name="' + esc(c.name) + '" data-phone="' + esc(c.phone) + '">' +
                esc(c.name) + (c.phone ? '<span>' + esc(c.phone) + "</span>" : "") + "</button>";
            }).join("");
          }
          box.classList.remove("hidden");
        })
        .catch(function () {});
    }, 180);
  });
  $("bkResults").addEventListener("click", function (event) {
    var btn = event.target.closest(".book-result");
    if (!btn) return;
    setPicked({ id: parseInt(btn.dataset.id, 10), name: btn.dataset.name, phone: btn.dataset.phone });
    $("bkSearch").value = btn.dataset.name;
  });
  $("bkNewToggle").addEventListener("click", function () {
    setPicked(null);
    $("bkNew").classList.toggle("hidden");
  });

  function fail(message) {
    var err = $("bkErr");
    err.textContent = message;
    err.classList.remove("hidden");
  }

  $("bookSave").addEventListener("click", function () {
    $("bkErr").classList.add("hidden");
    var payload = {
      staff_member_id: parseInt($("bkMember").value, 10),
      service_id: parseInt($("bkService").value, 10),
      date: $("bkDate").value,
      time: $("bkTime").value,
    };
    if (pickedClient) {
      payload.client_id = pickedClient.id;
    } else if (!$("bkNew").classList.contains("hidden")) {
      payload.new_client = {
        first_name: $("bkFirst").value.trim(),
        last_name: $("bkLast").value.trim(),
        phone: $("bkPhone").value.trim(),
      };
      if (!payload.new_client.first_name && !payload.new_client.last_name) {
        fail("Enter the new client's name, or pick an existing client.");
        return;
      }
    } else {
      fail("Pick a client from the search, or add a new client.");
      return;
    }
    if (!payload.date || !payload.time) { fail("Pick a date and a start time."); return; }
    var tokenEl = modal.querySelector('input[name="csrfmiddlewaretoken"]');
    fetch("/daybook/book/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": tokenEl ? tokenEl.value : "",
      },
      body: JSON.stringify(payload),
    }).then(function (r) {
      return r.json().then(function (data) { return { ok: r.ok, data: data }; });
    }).then(function (res) {
      if (res.ok && res.data.ok) {
        /* On the day book itself, the new block should simply
           appear — a full page load to show one booking is the
           old world's manners. The daybook claims the event;
           anywhere else, navigate as before. */
        var ev = new CustomEvent("os:booked", {
          detail: { id: res.data.appointment_id, date: res.data.date, handled: false },
        });
        document.dispatchEvent(ev);
        if (ev.detail.handled) {
          hide();
        } else {
          window.location.href = "/?date=" + res.data.date;
        }
      } else {
        fail((res.data && res.data.error) || "That booking did not save — try again.");
      }
    }).catch(function () { fail("That booking did not save — try again."); });
  });

  openBtn.addEventListener("click", show);
  $("bookClose").addEventListener("click", hide);
  $("bookCancel").addEventListener("click", hide);
  modal.addEventListener("click", function (event) {
    if (event.target === modal) hide();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !modal.classList.contains("hidden")) hide();
  });
})();
