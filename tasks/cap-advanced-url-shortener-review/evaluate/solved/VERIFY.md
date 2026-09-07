Verify app.py by running the live app checks for shorten, redirect, stats, pending review, duplicate alias handling, and bad URL cases.

Test result expectations: /s/docs redirects and increments stats, /s/local-admin is forbidden until approved, invalid filters fail, and a fresh app import can still read sqlite data.