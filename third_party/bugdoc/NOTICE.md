# BugDoc (vendored)

- Source: https://github.com/VIDA-NYU/BugDoc
- Commit: 75e3d262c6b6199cb6864a0ac6cfc801ec070c01 (2026-07-13)
- License: MIT (see `LICENSE`, copyright 2021 VIDA-NYU)
- Paper: Lourenço, R.; Freire, J.; Shasha, D. BugDoc: Algorithms to Debug Computational Processes. SIGMOD 2020.
  DOI 10.1145/3318464.3389763; arXiv:2004.06530.
- Contents: `bugdoc/` = `bugdoc_api/bugdoc/` unmodified; `upstream_tests/` = `test/test_standalone.py`,
  `test/budget_test.py`, `examples/standalone_example.py`; `docs/` = upstream README and standalone notes.
- Modifications: none. Import by putting `third_party/bugdoc` on `sys.path`. Runtime needs `future`, `six` and `pillow` (tree drawing in DDT);
  `zmq` is imported only by the worker-based (non-standalone) algorithms, which this benchmark does not use.
