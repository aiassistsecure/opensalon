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
      '<div class="rail-actions">' +
      '<button type="button" class="btn-grad grow" disabled title="Check-in arrives with the attendance lane">✓ Check In</button>' +
      '<button type="button" class="btn-ghost" disabled title="Rescheduling arrives with the booking lane">Reschedule</button>' +
      '<button type="button" class="btn-ghost" disabled title="Editing arrives with the booking lane">✎ Edit</button></div>';
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
          /* The dragged element lives on <body> while it flies —
             it must die here, whatever happens next. A swap only
             replaces the layout; a body-level tile left behind is
             the stuck duplicate that haunted the first build. */
          tile.remove();
          var changed = target.member !== originMember || target.startMin !== startMin0;
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

  function refreshDay() {
    if (!currentDate || !fragmentBase) { window.location.reload(); return; }
    delete hotCache[currentDate];
    fetchFragment(currentDate).then(function () {
      swapTo(currentDate, false);
    }).catch(function () { window.location.reload(); });
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

    if (railBody) {
      railBody.addEventListener("click", function (event) {
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
