# Local data identity during Windows contention

The desktop stores one opaque UUID in the selected local data directory. It
uses that directory's device/inode identity, an exclusive creator lock and an
atomic metadata publication. Aliases and renames keep the identity; copied
metadata receives a different identity. A missing root is never created here.

Readers and lock contenders now share a three-second contention deadline.
This outlasts the existing approximately 1.5-second Windows rename retry window,
including short scanner or sharing conflicts. Previously a caller could return
unknown after 200/500 ms while another legitimate creator was still publishing.
The concurrent-startup test therefore sometimes contained both a UUID and an
unknown result; a set of size two alone did not establish two generated UUIDs.

A second publication transition is handled independently: an initial open can
report missing just before another creator publishes the complete file. If the
subsequent no-follow existence check finds a regular file, the reader retries
the complete verified read within the same deadline. It does not return the
stale missing-file error or follow a link. A deterministic regression reproduces
this race even when the longer contention deadline is already installed.

The deadline remains bounded. Invalid, oversized, inaccessible or linked
metadata, a changed root, and an unresolved stale creator lock still leave the
identity unknown. Do not replace this with a path-derived identifier or delete
another process's lock to force success. Once the filesystem contention clears,
a later normal read can recover the persisted identity.
