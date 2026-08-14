"""Minimal readline stub to work around a broken conda readline C-extension.

The env's libreadline segfaults on `import readline`, which blocks pytest's
internal `_readline_workaround`.  This pure-Python stub satisfies pytest's
`import readline` so the test runner works.  It exposes a trivial readline API.
Caveat: interactive/completion features are no-ops.  Only used for pytest runs
(added to PYTHONPATH); the scientific pipeline never imports readline.
"""
def parse_and_bind(*_a, **_k):
    return None
def get_completer(*_a, **_k):
    return None
def set_completer(*_a, **_k):
    return None
def set_completer_delims(*_a, **_k):
    return None
def add_history(*_a, **_k):
    return None
def read_history_file(*_a, **_k):
    return None
def write_history_file(*_a, **_k):
    return None
def get_current_history_length(*_a, **_k):
    return 0
__all__ = []
