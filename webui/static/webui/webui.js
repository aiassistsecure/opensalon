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
})();
