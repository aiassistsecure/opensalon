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

  /* ---- Sidebar collapse -------------------------------------------
     The server renders the persisted state from the os_sidebar
     cookie (see webui.context_processors), so the width is right on
     first paint. The toggle's form posts + redirects without JS;
     with JS we flip in place — set the same cookie, swap the class,
     and re-arm the form so the next press goes the other way. */
  var sideForm = document.querySelector("form[data-sidebar-toggle]");
  if (sideForm) {
    sideForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var rail = !document.body.classList.contains("is-rail");
      document.body.classList.toggle("is-rail", rail);
      document.cookie = "os_sidebar=" + (rail ? "rail" : "full")
        + "; Max-Age=31536000; Path=/; SameSite=Lax";
      var stateInput = sideForm.querySelector('input[name="state"]');
      if (stateInput) stateInput.value = rail ? "full" : "rail";
      var sideBtn = sideForm.querySelector("button");
      if (sideBtn) {
        var sideLabel = rail ? "Expand sidebar" : "Collapse sidebar";
        sideBtn.setAttribute("aria-expanded", String(!rail));
        sideBtn.setAttribute("aria-label", sideLabel);
        sideBtn.title = sideLabel;
        var glyph = sideBtn.querySelector("span");
        if (glyph) glyph.textContent = rail ? "»" : "«";
      }
    });
  }

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

  /* ---- Selection + the action bar ----------------------------------
     Normal mode, first click on a block: select it — the action
     bar's chip fills with the appointment and its buttons arm
     (Pay / Add Service / Notes / Copy link to the block's own pages;
     Check In / Confirm point their POST forms at the action
     endpoint). Clicking the selected block again follows its link
     into the breakdown. */
  var chip = document.getElementById("selchip");
  var selected = null;

  function staffNameFor(block) {
    var column = block.closest(".db-column");
    var columns = Array.prototype.slice.call(wrap.querySelectorAll(".db-column"));
    var heads = wrap.querySelectorAll(".db-staff-name");
    var idx = columns.indexOf(column);
    return idx >= 0 && heads[idx] ? heads[idx].textContent.trim() : "";
  }

  function select(block) {
    if (selected) selected.classList.remove("is-selected");
    selected = block;
    block.classList.add("is-selected");
    var id = block.getAttribute("data-appt-id");
    var price = block.getAttribute("data-price");
    if (chip) {
      chip.textContent = "";
      chip.appendChild(document.createTextNode("Selected · "));
      var bold = document.createElement("b");
      bold.textContent = block.getAttribute("data-time") + " — " + block.getAttribute("data-client");
      chip.appendChild(bold);
      chip.appendChild(document.createTextNode(
        " · " + block.getAttribute("data-service") + " · " + staffNameFor(block)));
      if (price) {
        chip.appendChild(document.createTextNode(" · "));
        var priceEl = document.createElement("b");
        priceEl.textContent = price;
        chip.appendChild(priceEl);
      }
    }
    if (!id) return;
    var links = { pay: "/appointment/" + id + "/close-out/",
                  add: "/appointment/" + id + "/add-service/",
                  notes: "/appointment/" + id + "/",
                  copy: "/appointment/copy/?source=" + id };
    Object.keys(links).forEach(function (key) {
      var el = wrap.ownerDocument.querySelector('.abtn[data-act="' + key + '"]');
      if (el) { el.setAttribute("href", links[key]); el.removeAttribute("aria-disabled"); }
    });
    var forms = { "checkin-form": "check-in", "confirm-form": "confirm" };
    Object.keys(forms).forEach(function (formId) {
      var form = document.getElementById(formId);
      if (form) {
        form.setAttribute("action", "/appointment/" + id + "/action/" + forms[formId] + "/");
        var btn = form.querySelector("button");
        if (btn) btn.disabled = false;
      }
    });
  }

  /* ---- The now-line (today's view only) ---- */
  (function nowLine() {
    var columns = wrap.querySelectorAll(".db-column");
    if (!columns.length) return;
    var now = new Date();
    var iso = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0")
      + "-" + String(now.getDate()).padStart(2, "0");
    if (columns[0].getAttribute("data-date") !== iso) return;
    var minutes = now.getHours() * 60 + now.getMinutes();
    if (minutes < DAY_START_MIN || minutes > DAY_END_MIN) return;
    var grid = wrap.querySelector(".daybook");
    var column = columns[0];
    var line = document.createElement("div");
    line.className = "db-nowline";
    line.style.left = column.offsetLeft + "px";
    line.style.top = (column.offsetTop
      + (minutes - DAY_START_MIN) / (DAY_END_MIN - DAY_START_MIN) * column.offsetHeight) + "px";
    grid.appendChild(line);
  })();

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

    /* Normal mode: a block's first click selects it for the action
       bar; clicking the selected block follows its breakdown link.
       Empty space sets an appointment. Blocks, breaks and band
       labels are not empty space. */
    if (block) {
      if (block !== selected) { event.preventDefault(); select(block); }
      return;
    }
    if (event.target.closest(".break-block")) return;
    if (column) {
      var newUrl = "/appointment/new/?staff=" + encodeURIComponent(column.getAttribute("data-staff-id"))
        + "&date=" + encodeURIComponent(column.getAttribute("data-date"))
        + "&start=" + encodeURIComponent(slotTime(column, event));
      window.location.href = newUrl;
    }
  });
})();
