# Architectural Decision Record: Derived Document Completion (K2 Rule)

Date: 2026-08-02  
Status: Approved & Permanent (User Decision K2)

## Context & Decision
In the Document Center (Belge Merkezi), manual checkbox ticking (`done: 1` without evidence) has been permanently removed.

Document requirement completion (`done`) is strictly derived by the system:
- `done = True` if one or more valid files are uploaded to the requirement OR a mandatory written waiver reason (`waiver_reason`) is recorded.
- Legacy records with manual ticks but no files or written waiver reasons display as `unverified` with `done = False`.

Manual check-offs are no longer accepted as valid verification evidence.
