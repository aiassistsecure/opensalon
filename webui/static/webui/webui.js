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

  function renderRail(d) {
    if (!railBody || !d) return;
    var contact = [d.client_email, d.client_phone].filter(Boolean).map(esc).join(" · ");
    var stack = d.stack.map(function (item) {
      return '<div class="stack-row' + (item.current ? " current" : "") + '">' +
        '<span class="stack-dot"></span>' +
        '<span class="stack-name">' + esc(item.service) + "</span>" +
        '<span class="stack-dur">' + esc(item.duration_label) + "</span>" +
        '<span class="stack-price">' + esc(item.price_label || "—") + "</span></div>";
    }).join("");
    var history = d.history.length ? d.history.map(function (h) {
      return '<div class="hrow"><span class="hrow-date">' + esc(h.date_label) + " · " +
        esc(h.time_label) + '</span><span class="hrow-svc">' + esc(h.service) +
        '</span><span class="hrow-meta">' + esc(h.stylist) + " · " + esc(h.status_label) +
        "</span></div>";
    }).join("") : '<p class="rail-empty">No other appointments on file.</p>';
    var apptNotes = d.appt_notes.length ? d.appt_notes.map(function (n) {
      return '<div class="note-box">' + esc(n) + "</div>";
    }).join("") : '<p class="rail-empty">No appointment notes.</p>';
    var clientNotes = d.client_notes.length ? d.client_notes.map(function (n) {
      return '<div class="note-box">' + esc(n) + "</div>";
    }).join("") : '<p class="rail-empty">No client record notes.</p>';

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
      esc(d.price_label || "—") + "</span></div>" +
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
      ((d.actions && d.actions.length)
        ? '<div class="rail-actions">' + d.actions.map(function (a) {
            return '<button type="button" class="' +
              (a.primary ? "btn-grad grow" : "btn-ghost") +
              '" data-status-action="' + esc(a.status) + '" data-appt="' +
              esc(d.id) + '">' + esc(a.label) + "</button>";
          }).join("") + "</div>" +
          '<p class="rail-hint">Drag a block on the book to move it — drop it on another stylist to reassign.</p>'
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
  function bindDrag() {
    document.querySelectorAll(".db-column .appt-block").forEach(function (tile) {
      tile.addEventListener("pointerdown", function (event) {
        if (event.button !== undefined && event.button !== 0) return;
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
          tile.style.left = (e.clientX - grabDX) + "px";
          tile.style.top = (e.clientY - grabDY) + "px";
          var el = document.elementFromPoint(e.clientX, e.clientY);
          var tcol = el ? el.closest(".db-column") : null;
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
            fmt(dayStartMin + snapped) + (target.member !== originMember ? " · new stylist" : "");
        }
        function finish(commit) {
          tile.removeEventListener("pointermove", onMove);
          tile.removeEventListener("pointerup", onUp);
          tile.removeEventListener("pointercancel", onCancel);
          tile.removeEventListener("lostpointercapture", onCancel);
          if (!engaged) return;
          if (ghost) ghost.remove();
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
    }).then(function () { refreshDay(apptId); })
      .catch(function () { refreshDay(apptId); });
  }

  /* Bind everything that lives inside the day-book layout. Runs
     on first load and again after every hot-range swap, because a
     swap replaces the layout node wholesale. */
  function bindBook() {
    sweepStrays();
    railEl = document.getElementById("detailRail");
    railBody = document.getElementById("railBody");
    payloads = {};
    var dataEl = document.getElementById("rail-data");
    if (dataEl) {
      try { payloads = JSON.parse(dataEl.textContent); } catch (e) { payloads = {}; }
    }
    selected = null;

    document.querySelectorAll(".appt-block, .acard").forEach(function (block) {
      block.addEventListener("mouseenter", function () {
        if (window.innerWidth > 760) renderRail(payloads[block.dataset.appt]);
      });
      block.addEventListener("click", function () { choose(block, true); });
      block.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          choose(block, true);
        }
      });
    });

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
    layoutEl.replaceWith(fresh);
    layoutEl = fresh;
    currentDate = iso;
    bindBook();
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
  var model = { days: {}, staff: [] };
  var filtersActive = /[?&](cat|status)=[^&]/.test(window.location.search);

  function buildModel(pack) {
    if (pack && pack.days) model = { days: pack.days, staff: pack.staff || [] };
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

  function repaintDay() {
    var entries = modelDay();
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
        if (!el) return;
        if (el.parentElement !== col) col.appendChild(el);
        el.style.top = ((e.start_min - 480) / 720 * 100) + "%";
        el.style.height = Math.max((e.end_min - e.start_min) / 720 * 100, 4.0) + "%";
        if (info) {
          el.style.left = "calc(" + info.left + "% + 5px)";
          el.style.width = "calc(" + info.width + "% - 10px)";
        }
        el.dataset.startMin = String(e.start_min - 480);
        var dur = e.end_min - e.start_min;
        el.classList.toggle("mini", dur < 45 || (info && info.overlap >= 3 && dur < 90));
        el.classList.toggle("micro", dur < 30);
        var timeEl = el.querySelector(".b-time");
        if (timeEl) timeEl.textContent = fmtClock(e.start_min) + " – " + fmtClock(e.end_min);
      });
      factors.push(Math.min(3, maxOverlap));
    });
    var tracks = "var(--gutter) " + factors.map(function (f) {
      return "minmax(calc(var(--colunit) * " + f + "), " + f + "fr)";
    }).join(" ");
    layoutEl.querySelectorAll(".colheads, .gridwrap").forEach(function (el) {
      el.style.setProperty("--tracks", tracks);
    });
    return true;
  }

  function applyMove(id, staffId, startMin) {
    var entries = modelDay();
    if (!entries) return false;
    var found = null;
    entries.forEach(function (e) { if (e.id === id) found = e; });
    if (!found) return false;
    var dur = found.end_min - found.start_min;
    found.staff_id = staffId;
    found.start_min = startMin;
    found.end_min = startMin + dur;
    return repaintDay();
  }

  var shadowPending = {};
  var shadowTimer = null;
  function queueShadow(id) {
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
    Promise.all(jobs).then(function () {
      /* If another drag is already in hand, let it finish and
         reconcile then — never swap the floor mid-gesture. */
      if (ids.length && !document.querySelector(".appt-block.dragging")) {
        refreshDay(parseInt(ids[ids.length - 1], 10));
      }
    });
  }

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
  function pollPack() {
    if (pollBusy || document.hidden) return;
    if (document.querySelector(".appt-block.dragging")) return;
    pollBusy = true;
    var url = "/daybook/pack/?date=" + encodeURIComponent(currentDate || "") +
      (packVersion ? "&stamp=" + encodeURIComponent(packVersion) : "");
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.version) return;
        if (data.days) buildModel(data);
        if (packVersion === null) {
          packVersion = data.version;
        } else if (data.changed) {
          packVersion = data.version;
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
        window.location.href = "/?date=" + res.data.date;
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
