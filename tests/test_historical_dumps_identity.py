import json

import pytest

from habench.historical import dumps_identity as d


def test_digests_ignore_only_the_stamp_line(tmp_path):
    a, b, c = tmp_path / "a.sql", tmp_path / "b.sql", tmp_path / "c.sql"
    a.write_bytes(b"INSERT 1;\n-- Dump completed on 2025-06-05\n")
    b.write_bytes(b"INSERT 1;\n-- Dump completed on 2025-07-11\n")
    c.write_bytes(b"INSERT 2;\n-- Dump completed on 2025-06-05\n")
    ra, na = d.digests(a)
    rb, nb = d.digests(b)
    assert ra != rb and na == nb
    assert d.digests(c)[1] != na


@pytest.mark.dumps
def test_v1_equals_0605_except_stamp():
    committed = json.loads(d.OUT_PATH.read_text(encoding="utf-8"))
    assert (committed["files_in_common"], committed["normalized_equal"], committed["raw_equal"]) == (33, 33, 0)
    assert json.loads(json.dumps(d.compare(), sort_keys=True)) == committed
