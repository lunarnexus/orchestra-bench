# Run Prompt
Read `PRD.md` and `fixture/`. Ask the parent/coordinator to dispatch the reviewer role via Orchestra, then save the final review to `answer.md`.
Dispatch and proceed until finished.

## Completion requirement
If you dispatch a worker, wait for the worker result before finishing. The run is not complete until `answer.md` exists in the current directory. After the worker returns, write its final role deliverable to `answer.md`. If dispatch is unavailable or does not return usable content, produce the best scoped `reviewer` deliverable yourself in `answer.md` rather than exiting without the file.
Do not end by saying you are waiting for a worker. If no worker result is available before you finish, write the scoped deliverable yourself to `answer.md` immediately.
