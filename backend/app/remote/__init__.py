"""AKASHI remote presence: secure device sessions for thin clients.

Reusable foundation (Spatial Lab is its first consumer):

* ``scopes``        — owner-granted permissions a device can hold
* ``capabilities``  — dynamic per-session capability reports + provider queries
* ``identity``      — P-256 device keys and single-use challenge handshakes
* ``sessions``      — short-lived session credentials, lifecycle, outboxes
* ``flow``          — rate limits and clock-independent staleness
* ``protocol``      — the ``akashi.remote/1`` envelope
* ``audit``         — hash-chained audit trail (``app.history.ActionLog``)
* ``hub``           — receive pipeline, channels, revocation
"""
