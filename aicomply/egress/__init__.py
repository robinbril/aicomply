"""Static egress scan: what leaves the system, to whom, and carrying what.

Reads source trees, built JavaScript bundles and Electron .asar archives
without running them, the static half of what a reverse-engineering tool such
as REA does. For a native binary, run REA (github.com/morluto/rea) and feed
its endpoint list in with --extra-hosts.
"""

from aicomply.egress.scanner import scan  # noqa: F401
