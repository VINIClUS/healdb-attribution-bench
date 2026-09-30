import pytest

from habench.data import dumps

HEADER = """-- dump
CREATE TABLE `t` (
  `id` int NOT NULL,
  `name` varchar(20) DEFAULT NULL,
  `score` double DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB;
"""


def write(tmp_path, body: str):
    p = tmp_path / "healdb_t.sql"
    p.write_text(HEADER + body, encoding="utf-8", newline="\n")
    return p


def read(tmp_path, body: str):
    return list(dumps.rows("V1", "t", write(tmp_path, body)))


def test_columns(tmp_path):
    assert dumps.columns("V1", "t", write(tmp_path, "")) == ["id", "name", "score"]


def test_basic_types(tmp_path):
    got = read(tmp_path, "INSERT INTO `t` VALUES (1,'a',0.6668867468833923),(-2,NULL,-1.5e-3);\n")
    assert got == [[1, "a", 0.6668867468833923], [-2, None, -0.0015]]
    assert type(got[0][0]) is int and type(got[1][2]) is float


def test_float_exponent_and_int_like(tmp_path):
    got = read(tmp_path, "INSERT INTO `t` VALUES (1,'x',1E5),(2,'y',3e+2),(3,'z',7);\n")
    assert [r[2] for r in got] == [1e5, 300.0, 7]
    assert type(got[2][2]) is int


def test_escapes(tmp_path):
    body = "INSERT INTO `t` VALUES (1,'a\\0b\\nc\\rd\\te\\bf\\Zg\\'h\\\\i\\\"j\\qk''l',NULL);\n"
    assert read(tmp_path, body)[0][1] == "a\0b\nc\rd\te\bf\x1ag'h\\i\"jqk'l"


def test_binary_prefix_and_delimiters_in_strings(tmp_path):
    got = read(tmp_path, "INSERT INTO `t` VALUES (1,_binary 'a),(2,',1.0);\n")
    assert got == [[1, "a),(2,", 1.0]]


def test_multiple_insert_lines_and_other_lines(tmp_path):
    body = (
        "LOCK TABLES `t` WRITE;\n"
        "INSERT INTO `t` VALUES (1,'a',1.0),(2,'b',2.0);\n"
        "INSERT INTO `other` VALUES (9,'z',9.0);\n"
        "INSERT INTO `t` VALUES (3,'c',NULL);\n"
    )
    assert [r[0] for r in read(tmp_path, body)] == [1, 2, 3]


def test_records(tmp_path):
    p = write(tmp_path, "INSERT INTO `t` VALUES (1,'a',2.5);\n")
    assert list(dumps.records("V1", "t", p)) == [{"id": 1, "name": "a", "score": 2.5}]


def test_surrogateescape_and_newline_preserved(tmp_path):
    p = tmp_path / "healdb_t.sql"
    p.write_bytes(HEADER.encode() + b"INSERT INTO `t` VALUES (1,'a\r\xffb\xc3\xa9',NULL);\n")
    v = list(dumps.rows("V1", "t", p))[0][1]
    assert v == "a\r\udcffbé"
    assert v.encode("utf-8", "surrogateescape") == b"a\r\xffb\xc3\xa9"


@pytest.mark.parametrize(
    "body",
    [
        "INSERT INTO `t` VALUES (1,'a',0x1F);\n",
        "INSERT INTO `t` VALUES (1,b'101',1.0);\n",
        "INSERT INTO `t` VALUES (1,garbage,1.0);\n",
        "INSERT INTO `t` VALUES 1,'a',1.0;\n",
        "INSERT INTO `t` VALUES (1,'a',1.0)(2,'b',2.0);\n",
        "INSERT INTO `t` VALUES (1,'a',1.0)\n",
        "INSERT INTO `t` VALUES (1,'unterminated,1.0);\n",
    ],
)
def test_garbage_raises(tmp_path, body):
    with pytest.raises(ValueError):
        read(tmp_path, body)


def test_path_uses_current_dumps_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(dumps, "DUMPS_DIR", tmp_path)
    assert dumps.path("V1", "hd_x") == tmp_path / dumps.SOURCES["V1"] / "healdb_hd_x.sql"
    assert dumps.path("rel/dir", "hd_x") == tmp_path / "rel/dir" / "healdb_hd_x.sql"


@pytest.mark.dumps
def test_real_v1_medication_disease_extend_columns():
    cols = dumps.columns("V1", "hd_medication_disease_extend")
    assert cols[:3] == ["id_med_disease", "id_medication", "cd_icd_full"]
