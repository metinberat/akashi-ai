# AKASHI Windows Agent

The agent is a separate, normal-user process and binds to `127.0.0.1` only. It
does not expose a generic command or PowerShell endpoint. Every action is named,
validated, classified as `safe` or `confirm`, and constrained to configured
filesystem roots and discovered application executables.

See the repository development and security documentation for setup and pairing.
