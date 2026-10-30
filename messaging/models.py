# Messaging stores nothing of its own in this foundation slice:
# opt-in state lives on clients.Client (the one source of truth)
# and reminders are sent, not persisted. This module exists only
# so Django registers the app.
