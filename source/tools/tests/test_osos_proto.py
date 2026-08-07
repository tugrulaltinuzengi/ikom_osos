import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import osos_proto as p


def test_version_is_two():
    assert p.PROTO_V == 2


def test_build_modem_topics():
    assert p.modem_topic("gw-01", "status") == "osos/m/gw-01/status"
    assert p.modem_topic("gw-01", "cmd") == "osos/m/gw-01/cmd"


def test_build_analyzer_topic():
    assert p.analyzer_topic("gw-01", "an-07", "telemetry") == \
        "osos/m/gw-01/a/an-07/telemetry"


def test_parse_analyzer_telemetry():
    assert p.parse("osos/m/gw-01/a/an-07/telemetry") == \
        ("analyzer", "gw-01", "an-07", "telemetry")


def test_parse_modem_status():
    assert p.parse("osos/m/gw-01/status") == ("modem", "gw-01", None, "status")


def test_parse_tree():
    assert p.parse("osos/tree") == ("tree", None, None, "tree")


def test_parse_legacy_has_no_m_segment():
    assert p.parse("osos/dkm440-gw1/telemetry") == \
        ("legacy", "dkm440-gw1", None, "telemetry")


def test_reserved_m_segment_is_not_legacy():
    # osos/m/telemetry must NOT be read as a legacy gateway named "m"
    assert p.parse("osos/m/telemetry")[0] == "unknown"


def test_parse_rejects_foreign_prefix():
    assert p.parse("other/m/gw-01/status")[0] == "unknown"
