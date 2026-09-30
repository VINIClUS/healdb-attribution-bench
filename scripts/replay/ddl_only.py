"""Print a mysqldump file up to (not including) its first `LOCK TABLES` line: session setup plus DROP/CREATE TABLE.

Usage: python ddl_only.py <dump.sql>   (streams the file; the data section is never read)
"""

import sys

with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
    for line in fh:
        if line.startswith("LOCK TABLES"):
            break
        sys.stdout.write(line)
