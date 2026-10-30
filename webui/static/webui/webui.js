/* OpenSalon webui — small vanilla JS, only where it earns its keep.
   Everything else is server-rendered and GET-driven. */
(function () {
  "use strict";

  /* Day book date control: picking a date jumps straight to that day,
     keeping any active filters (the form carries them as hidden
     fields). */
  document.querySelectorAll("form[data-date-jump]").forEach(function (form) {
    var input = form.querySelector('input[type="date"]');
    if (!input) return;
    input.addEventListener("change", function () {
      if (input.value) form.submit();
    });
  });

  /* ---- The day book click model -----------------------------------
     Normal mode: clicking a block opens its breakdown (a plain link);
     clicking empty column space opens the booking form prefilled with
     that stylist and the clicked time.
     Copy mode (the ⧉ Copy toggle): clicking a block picks the visit
     up; clicking any slot then opens the copy form targeted there.
     Esc leaves copy mode. All placement is confirmed server-side —
     this script only navigates. */
  var wrap = document.getElementById("daybook-wrap");
  var toggle = document.getElementById("copy-toggle");
  var status = document.getElementById("copy-status");
  if (!wrap) return;

  var DAY_START_MIN = 8 * 60, DAY_END_MIN = 20 * 60;

  function slotTime(column, event) {
    var rect = column.getBoundingClientRect();
    var ratio = (event.clientY - rect.top) / rect.height;
    var minutes = DAY_START_MIN + ratio * (DAY_END_MIN - DAY_START_MIN);
    minutes = Math.round(minutes / 15) * 15;
    minutes = Math.max(DAY_START_MIN, Math.min(DAY_END_MIN - 15, minutes));
    var hh = String(Math.floor(minutes / 60)).padStart(2, "0");
    var mm = String(minutes % 60).padStart(2, "0");
    return hh + ":" + mm;
  }

  function say(text) {
    if (!status) return;
    status.hidden = !text;
    status.textContent = text || "";
  }

  var armed = false;
  var pickedId = null;
  var pickedEl = null;

  function setArmed(on) {
    armed = on;
    wrap.classList.toggle("copy-armed", on);
    if (toggle) {
      toggle.setAttribute("aria-pressed", String(on));
      toggle.classList.toggle("is-on", on);
    }
    if (!on) {
      if (pickedEl) pickedEl.classList.remove("is-picked");
      pickedEl = null;
      pickedId = null;
      say("");
    } else {
      say("Copy mode: click an appointment to pick it up, then click the slot where its copy goes. Esc to leave copy mode.");
    }
  }

  if (toggle) {
    toggle.addEventListener("click", function () { setArmed(!armed); });
  }
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && armed) setArmed(false);
  });

  wrap.addEventListener("click", function (event) {
    var block = event.target.closest(".appt-block");
    var column = event.target.closest(".db-column");

    if (armed) {
      if (block && block.getAttribute("data-appt-id")) {
        event.preventDefault();
        if (pickedEl) pickedEl.classList.remove("is-picked");
        pickedEl = block;
        pickedId = block.getAttribute("data-appt-id");
        block.classList.add("is-picked");
        say("Picked up. Now click the slot where the copy goes — any stylist, any time today.");
        return;
      }
      if (column && pickedId) {
        event.preventDefault();
        var url = "/appointment/copy/?source=" + encodeURIComponent(pickedId)
          + "&staff=" + encodeURIComponent(column.getAttribute("data-staff-id"))
          + "&date=" + encodeURIComponent(column.getAttribute("data-date"))
          + "&start=" + encodeURIComponent(slotTime(column, event));
        window.location.href = url;
        return;
      }
      if (column) {
        say("Pick an appointment up first — click the visit you want to copy.");
      }
      return;
    }

    /* Normal mode: empty space sets an appointment. Blocks, breaks
       and band labels are not empty space. */
    if (block) return; /* the block's own link handles it */
    if (event.target.closest(".break-block")) return;
    if (column) {
      var newUrl = "/appointment/new/?staff=" + encodeURIComponent(column.getAttribute("data-staff-id"))
        + "&date=" + encodeURIComponent(column.getAttribute("data-date"))
        + "&start=" + encodeURIComponent(slotTime(column, event));
      window.location.href = newUrl;
    }
  });
})();
