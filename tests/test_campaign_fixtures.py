"""Synthetic split manifest shared by the campaign tests (no test functions here)."""

import functools
import tempfile
from pathlib import Path

MANIFEST_CSV = """\
group_id,partition,medications,n_medications,stratum,inclusion_prob
gaaaaaaaaaaa1,dev,101;102,2,s1,0.5
gaaaaaaaaaaa2,cal,201,1,s2,0.25
gaaaaaaaaaaa3,test,301;302;303,3,s1,0.5
gaaaaaaaaaaa4,reserve,401,1,s2,1.0
"""


@functools.cache
def manifest_path() -> Path:
    """The manifest written once per session to a temporary directory outside the repo."""
    path = Path(tempfile.mkdtemp(prefix="habench-campaign-")) / "split_manifest.csv"
    path.write_text(MANIFEST_CSV, encoding="utf-8")
    return path
