"""Modal scope: the enclave's fade law stays on the enclave's page.

The desk's report, 2026-11-02: after the morning pull the
day book broke state — click Checkout and nothing appears,
then every click anywhere does nothing; Notes does
nothing; only F5 unlocks the page; the server logs stay
clean. The same morning's booking test at the last
verified commit (#396) worked, so the bug rode in with the
commits between.

It was CSS, and it was the booking enclave (PR #402). The
enclave's done-modal fades in: its rules set .book-modal
to opacity:0, lifted to opacity:1 only by an .open class
the enclave's own script adds. But .book-modal is not the
enclave's class — it is the class of every modal in
base.html (checkout, new appointment, time clock), pages
that open their modals by removing .hidden and never heard
of .open. The enclave's rules sit later in the stylesheet
at equal specificity, so from #402 on, opening any modal
in the app painted a full-screen fixed overlay at
opacity 0: the modal and its card invisible, the overlay
real — catching every click meant for the page beneath
it, until a reload restored .hidden.

The law: a page's motion rules scope to that page's body,
the way the enclave's own primary button already did
(.book-body .btn-primary). The app's modals keep their own
.book-modal rule, the one that predates the enclave, and
no unscoped rule may set a modal's opacity again.
"""

from pathlib import Path

from django.test import TestCase

ROOT = Path(__file__).parent


class ModalScopeTests(TestCase):
    def setUp(self):
        self.css = (ROOT / "static" / "webui" / "webui.css").read_text()
        self.base = (ROOT / "templates" / "webui" / "base.html").read_text()

    def test_the_app_modals_share_the_book_modal_class(self):
        # The fact that makes scoping load-bearing: base.html's
        # three modals wear the enclave modal's class.
        for modal_id in ["checkoutModal", "bookModal", "clockModal"]:
            self.assertIn(f'class="book-modal hidden" id="{modal_id}"', self.base)

    def test_the_enclave_fade_rules_are_scoped_to_its_body(self):
        self.assertIn(".book-body .book-modal{position:fixed", self.css)
        self.assertIn(".book-body .book-modal[hidden]{display:none}", self.css)
        self.assertIn(".book-body .book-modal.open{opacity:1}", self.css)
        self.assertIn(".book-body .book-modal.open .book-done-card", self.css)

    def test_no_unscoped_rule_opacifies_the_app_modals(self):
        # The enclave block as it shipped in #402, verbatim —
        # it must never come back unscoped.
        self.assertNotIn("\n.book-modal{position:fixed", self.css)
        self.assertNotIn("\n.book-modal.open{opacity:1}", self.css)
        self.assertNotIn("\n.book-modal[hidden]{display:none}", self.css)

    def test_the_app_modals_own_rule_stands_untouched(self):
        # The pre-enclave rule: fixed, high, visible — the
        # styling the day book's modals were verified with.
        self.assertIn(
            ".book-modal {\n  position: fixed; inset: 0; z-index: 200;",
            self.css,
        )
