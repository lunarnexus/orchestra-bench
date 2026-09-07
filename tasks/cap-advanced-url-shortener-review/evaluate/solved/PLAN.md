Plan: implement app.py with the FastAPI route surface for homepage, POST /shorten, /s/{code}, /stats/{code}, /links, and admin review routes.

Steps: use sqlite tables for links and audit events so review and redirect state survives reload. The files to change are app.py and workflow notes; tests cover normal links, suspicious review, duplicate aliases, stats, and persistence.