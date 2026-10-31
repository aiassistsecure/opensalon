/* OpenSalon webui behaviour: the day book's detail rail, tabs,
   team-chip column jumps, and filter auto-submit.
   The rail is server-rendered for the day's first appointment;
   this script re-renders it from the JSON payloads the view
   embeds (#rail-data) when another appointment is chosen. On
   phones the rail is a bottom sheet (.rail.open). */
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[c];
    });
  }

  var railEl = document.getElementById("detailRail");
  var railBody = document.getElementById("railBody");
  var dataEl = document.getElementById("rail-data");
  var payloads = {};
  if (dataEl) {
    try { payloads = JSON.parse(dataEl.textContent); } catch (e) { payloads = {}; }
  }

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

  var selected = null;
  function choose(block, openSheet) {
    if (selected) selected.classList.remove("sel");
    selected = block;
    if (block) {
      block.classList.add("sel");
      renderRail(payloads[block.dataset.appt]);
      if (openSheet && railEl && window.innerWidth <= 760) railEl.classList.add("open");
    }
  }

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
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && railEl) railEl.classList.remove("open");
  });

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
})();
