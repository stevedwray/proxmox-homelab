# Hand-back Depends Test Workspace (throwaway)

Tests whether a completely separate `implement-step` invocation (a fresh
chat session with no memory of the first) correctly reads the hand-back
left by an earlier invocation to satisfy `depends_on`, rather than
needing that earlier session's memory. Delete this workspace once the
test is done.

## Step status

- `hbdep-01-write-first`: not started
- `hbdep-02-write-second`: not started
