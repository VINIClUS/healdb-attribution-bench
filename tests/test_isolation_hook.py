"""Audit-hook isolation. Every test that installs the hook does it in a child process: the hook is irreversible."""

from __future__ import annotations

import json
import secrets
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PREAMBLE = """
import json, os, sys
from pathlib import Path
from dataclasses import replace
import habench
from habench.views.isolation import default_policy, install

view, truth, scratch = (Path(p) for p in sys.argv[1:4])
policy = replace(
    default_policy(view, truth, extra_read=[Path(habench.__file__).parents[1]]), scratch=scratch
)

def denied(fn):
    try:
        fn()
    except PermissionError:
        return True
    return False

def ok(fn):
    try:
        fn()
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return True

results = {}
"""

EPILOGUE = "\nprint('RESULT' + json.dumps(results))\n"


@pytest.fixture
def world(tmp_path: Path) -> dict:
    view, truth, scratch = tmp_path / "view", tmp_path / "truth", tmp_path / "scratch"
    for d in (view, truth, scratch):
        d.mkdir()
    token = secrets.token_hex(16)
    (truth / "CANARY_TRUTH").write_text(token)
    (view / "a.txt").write_text("visible")
    (view / "link").symlink_to(truth / "CANARY_TRUTH")
    return {"view": view, "truth": truth, "scratch": scratch, "token": token, "root": tmp_path}


def run_child(world: dict, body: str, *, install_first: bool = True) -> dict:
    script = PREAMBLE + ("install(policy)\n" if install_first else "") + textwrap.dedent(body) + EPILOGUE
    proc = subprocess.run(
        [sys.executable, "-c", script, str(world["view"]), str(world["truth"]), str(world["scratch"])],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert world["token"] not in proc.stdout + proc.stderr
    line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT"))
    return json.loads(line[len("RESULT") :])


def test_reads(world):
    v, t, r = world["view"], world["truth"], world["root"]
    res = run_child(
        world,
        f"""
        results["view_read"] = ok(lambda: open({str(v / "a.txt")!r}).read())
        results["canary"] = denied(lambda: open({str(t / "CANARY_TRUTH")!r}).read())
        results["canary_osopen"] = denied(lambda: os.open({str(t / "CANARY_TRUTH")!r}, os.O_RDONLY))
        results["symlink"] = denied(lambda: open({str(v / "link")!r}).read())
        results["relative_escape"] = denied(lambda: open({str(v / ".." / "truth" / "CANARY_TRUTH")!r}).read())
        results["list_truth"] = denied(lambda: os.listdir({str(t)!r}))
        results["list_parent"] = denied(lambda: os.listdir({str(r)!r}))
        results["scandir_parent"] = denied(lambda: list(os.scandir({str(r)!r})))
        results["walk_parent"] = denied(lambda: os.scandir({str(r)!r}))
        results["list_view"] = ok(lambda: os.listdir({str(v)!r}))
        import glob
        results["glob_parent"] = denied(lambda: glob.glob({str(r / "*")!r}))
        results["glob_view"] = ok(lambda: glob.glob({str(v / "*")!r}))
        """,
    )
    assert res["view_read"] is True
    assert res["list_view"] is True and res["glob_view"] is True
    for key in (
        "canary",
        "canary_osopen",
        "symlink",
        "relative_escape",
        "list_truth",
        "list_parent",
        "scandir_parent",
        "walk_parent",
        "glob_parent",
    ):
        assert res[key] is True, key


def test_writes(world):
    v, s = world["view"], world["scratch"]
    res = run_child(
        world,
        f"""
        results["view_w"] = denied(lambda: open({str(v / "new.txt")!r}, "w"))
        results["view_append"] = denied(lambda: open({str(v / "a.txt")!r}, "a"))
        results["view_rplus"] = denied(lambda: open({str(v / "a.txt")!r}, "r+"))
        results["view_osopen"] = denied(lambda: os.open({str(v / "n2")!r}, os.O_WRONLY | os.O_CREAT))
        results["view_rm"] = denied(lambda: os.remove({str(v / "a.txt")!r}))
        results["view_mkdir"] = denied(lambda: os.mkdir({str(v / "d")!r}))
        results["scratch_w"] = ok(lambda: open({str(s / "out.txt")!r}, "w").write("x"))
        results["scratch_osopen"] = ok(lambda: os.close(os.open({str(s / "o2")!r}, os.O_WRONLY | os.O_CREAT)))
        results["scratch_mkdir"] = ok(lambda: os.mkdir({str(s / "d")!r}))
        """,
    )
    for key in ("view_w", "view_append", "view_rplus", "view_osopen", "view_rm", "view_mkdir"):
        assert res[key] is True, key
    for key in ("scratch_w", "scratch_osopen", "scratch_mkdir"):
        assert res[key] is True, (key, res[key])
    assert (s / "out.txt").read_text() == "x"
    assert (v / "a.txt").read_text() == "visible"
    assert not (v / "new.txt").exists()


def test_imports(world):
    res = run_child(
        world,
        """
        import importlib
        results["oracle"] = denied(lambda: importlib.import_module("habench.oracle"))
        results["pipeline_core"] = denied(lambda: importlib.import_module("habench.pipeline.core"))
        results["scenarios"] = denied(lambda: importlib.import_module("habench.scenarios"))
        results["from_import"] = denied(lambda: __import__("habench", fromlist=["oracle"]))
        results["methods_base"] = ok(lambda: importlib.import_module("habench.methods.base"))
        results["json"] = ok(lambda: importlib.import_module("json"))
        results["forbidden_not_loaded"] = not any(
            m.startswith(("habench.oracle", "habench.pipeline", "habench.scenarios")) for m in sys.modules
        )

        # Loading forbidden source by path under another name must also fail.
        import importlib.util
        src = Path(habench.__file__).parent / "oracle" / "__init__.py"
        def by_path():
            spec = importlib.util.spec_from_file_location("innocent", src)
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
        results["by_path"] = denied(by_path) if src.exists() else True
        """,
    )
    for key in ("oracle", "pipeline_core", "scenarios", "from_import", "forbidden_not_loaded", "by_path"):
        assert res[key] is True, key
    assert res["methods_base"] is True, res["methods_base"]
    assert res["json"] is True


def test_cached_import_does_not_fire_event(world):
    """Finding: only the first import of a module fires the `import` event; cached ones are silent."""
    res = run_child(
        world,
        """
        seen = []
        sys.addaudithook(lambda e, a: seen.append(a[0]) if e == "import" else None)
        import colorsys
        first = seen.count("colorsys")
        import colorsys
        results["first"] = first
        results["second"] = seen.count("colorsys") - first
        """,
        install_first=False,
    )
    assert res == {"first": 1, "second": 0}


def test_install_refuses_when_forbidden_module_loaded(world):
    res = run_child(
        world,
        """
        import habench.oracle
        try:
            install(policy)
        except RuntimeError as exc:
            results["refused"] = "habench.oracle" in str(exc)
        else:
            results["refused"] = False
        """,
        install_first=False,
    )
    assert res["refused"] is True


def test_sockets(world):
    res = run_child(
        world,
        """
        import socket
        results["new"] = denied(lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM))
        results["unix"] = denied(lambda: socket.socket(socket.AF_UNIX, socket.SOCK_STREAM))
        results["pair"] = denied(lambda: socket.socketpair())
        results["getaddrinfo"] = denied(lambda: socket.getaddrinfo("localhost", 80))
        results["create_connection"] = denied(lambda: socket.create_connection(("127.0.0.1", 9)))
        """,
    )
    assert all(v is True for v in res.values()), res


def test_processes(world):
    res = run_child(
        world,
        """
        import subprocess, pty
        results["run"] = denied(lambda: subprocess.run(["true"]))
        results["popen"] = denied(lambda: subprocess.Popen(["true"]))
        results["system"] = denied(lambda: os.system("true"))
        results["posix_spawn"] = denied(lambda: os.posix_spawn("/bin/true", ["true"], {}))
        results["spawnl"] = denied(lambda: os.spawnl(os.P_WAIT, "/bin/true", "true"))
        results["execv"] = denied(lambda: os.execv("/bin/true", ["true"]))
        results["fork"] = denied(lambda: os.fork())
        results["forkpty"] = denied(lambda: os.forkpty())
        results["pty_spawn"] = denied(lambda: pty.spawn(["true"]))
        """,
    )
    assert all(v is True for v in res.values()), res


def test_ctypes_denied(world):
    res = run_child(
        world,
        """
        import ctypes
        results["dlopen"] = denied(lambda: ctypes.CDLL(None))
        results["cdata"] = denied(lambda: ctypes.addressof(ctypes.c_int(1)))
        """,
    )
    assert all(v is True for v in res.values()), res


def test_preexisting_pipe_survives_install(world):
    """A Pipe (socketpair) created before install keeps working: send/recv fire no socket event."""
    res = run_child(
        world,
        """
        import multiprocessing as mp
        parent, child = mp.Pipe(duplex=True)
        install(policy)
        parent.send({"q": [1, 2, 3]})
        results["got"] = child.recv()
        child.send("pong")
        results["back"] = parent.recv()
        results["new_pipe_denied"] = denied(lambda: mp.Pipe(duplex=True))
        """,
        install_first=False,
    )
    assert res == {"got": {"q": [1, 2, 3]}, "back": "pong", "new_pipe_denied": True}
