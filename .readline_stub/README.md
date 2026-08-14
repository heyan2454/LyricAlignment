# readline stub (env workaround)

The `lyricalign-qwen` conda env's `readline` C-extension segfaults on
`import readline` (exit 139), which blocks `pytest` (its internal
`_readline_workaround` unconditionally imports readline during conftest
bootstrapping).  This is a machine/env defect, not a repo-code issue.

`.readline_stub/readline.py` is a minimal pure-Python readline that satisfies
pytest's import so the test runner works.  It is placed on `PYTHONPATH` **only**
for pytest invocations; the scientific pipeline never imports readline and is
unaffected.

Run tests with:
    PYTHONPATH=src:.readline_stub python -m pytest -q tests/<suite>

Interactive/completion features are no-ops under the stub (fine for CI/test).
If the env's readline is later repaired, this stub can be removed.
