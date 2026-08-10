# Storage Policy

Public upload filenames must be basenames only. Reject absolute paths, `..`, path separators, and extensions outside `.txt` and `.md`.

All accepted files live under `STORAGE_ROOT`. The upload record may store content in memory for this benchmark, but path calculation must remain safe.
