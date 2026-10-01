# Run Prompt
Work in the current directory. Edit the task files here.

Read `PRD.md`, consult the `kb/` policy and reference corpus, inspect the fixture, and finish Merchant Reconciliation Desk.
Create a plan and write to PLAN.md, then Dispatch and execute the plan.

Requirements:
- make the FastAPI app runnable with `python3 -m uvicorn app:app --host 127.0.0.1 --port 8123` from this workspace
- do not rely on undeclared Python packages; if the app needs a runtime dependency, list it in `requirements.txt`
- do not leave `uvicorn` or any long-running server process running at the end; if you start it to test, use a timeout/background process and stop it before finalizing
- implement the imports, reconciliation, exception review, audit history, reporting, and export behavior described in the PRD, following the named policy sections in the `kb/` corpus
- write `RULES_SUMMARY.md` mapping each required rule id from the PRD to the implementation behavior it affects before coding
- profile the fixture data and record material findings in `DATA_PROFILE.md` or in PLAN.md
- keep evaluator-only files out of the app
