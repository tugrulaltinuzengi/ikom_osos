"""The PC simulator speaks the profile protocol like the firmware does."""
import json
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

pytest.importorskip("paho.mqtt.client")

import fake_fleet as ff
import meterprofile as mp
import osos_proto as p

PROFILES = os.path.join(os.path.dirname(__file__), "..", "..", "meter-profiles")


class Rec:
    def __init__(self):
        self.out = []

    def __call__(self, topic, payload, retain=False):
        self.out.append((topic, payload, retain))
        return types.SimpleNamespace(rc=0)

    def last(self, topic):
        return [x for x in self.out if x[0] == topic][-1]


def make_fleet():
    args = types.SimpleNamespace(modems=1, analyzers=2, interval=5, host="x", port=1883,
                                 user="", password="")
    fl = ff.Fleet(args)
    rec = Rec()
    fl.pub = rec
    return fl, rec


def send(fl, mid, action, args, cid="c1"):
    msg = types.SimpleNamespace(topic=p.modem_topic(mid, "cmd"),
                                payload=json.dumps({"id": cid, "action": action, "args": args}))
    fl.on_message(None, None, msg)


def upload(fl, rec, name):
    for a, args in mp.wire_commands(mp.load_profile(os.path.join(PROFILES, name))):
        send(fl, "gw-01", a, args, cid=a)
        ack = rec.last(p.modem_topic("gw-01", "ack"))[1]
        assert ack["ok"], (a, ack)


def test_default_telemetry_is_the_dkm440_with_profile_fields():
    fl, rec = make_fleet()
    m = fl.modems["gw-01"]
    fl.publish_analyzer(m, m.analyzers[0])
    t = rec.last(p.analyzer_topic("gw-01", "an-01", "telemetry"))[1]
    assert t["profile"] == "dkm440" and t["profile_rev"] == 1 and t["meter_ok"] is True
    assert len(t["values"]) == 22
    assert 200 < t["values"]["MainBus_Voltage_L1"] < 260
    assert 49 < t["values"]["MainBus_Freq_L1"] < 51


def test_uploaded_profile_changes_the_values_of_the_assigned_analyzer_only():
    fl, rec = make_fleet()
    m = fl.modems["gw-01"]
    upload(fl, rec, "examples/sdm630.json")
    send(fl, "gw-01", "profile_assign", {"analyzer": "an-02", "profile": "sdm630"})
    assert rec.last(p.modem_topic("gw-01", "ack"))[1]["ok"]
    fl.publish_analyzer(m, m.analyzers[0])
    fl.publish_analyzer(m, m.analyzers[1])
    t1 = rec.last(p.analyzer_topic("gw-01", "an-01", "telemetry"))[1]
    t2 = rec.last(p.analyzer_topic("gw-01", "an-02", "telemetry"))[1]
    assert t1["profile"] == "dkm440" and "MainBus_Voltage_L1" in t1["values"]
    assert t2["profile"] == "sdm630" and "Voltage_L1" in t2["values"]
    assert "Energy_Import" in t2["values"] and t2["meter_ok"]
    assert 200 < t2["values"]["Voltage_L1"] < 260


def test_profile_topics_are_retained_and_follow_changes():
    fl, rec = make_fleet()
    upload(fl, rec, "examples/sdm630.json")
    topic, payload, retain = rec.last(p.modem_topic("gw-01", "profiles"))
    assert retain and {x["id"] for x in payload["profiles"]} == {"dkm440", "sdm630"}
    send(fl, "gw-01", "profile_assign", {"analyzer": "an-01", "profile": "sdm630"})
    t, blob, retain = rec.last(p.analyzer_topic("gw-01", "an-01", "profile"))
    assert retain and json.loads(blob)["id"] == "sdm630"
    # an-02 was not touched by that assignment
    last_an02 = [x for x in rec.out if x[0] == p.analyzer_topic("gw-01", "an-02", "profile")]
    assert not last_an02 or json.loads(last_an02[-1][1])["id"] == "dkm440"
    assert rec.last(p.modem_topic("gw-01", "profiles"))[1]["assign"] == {"an-01": "sdm630", "an-02": "dkm440"}


def test_profile_test_reads_the_virtual_meter():
    fl, rec = make_fleet()
    send(fl, "gw-01", "profile_test", {"analyzer": "an-01", "address": 260, "type": "f32"})
    ack = rec.last(p.modem_topic("gw-01", "ack"))[1]
    assert ack["ok"] and ack["detail"].startswith("raw=") and "value=2" in ack["detail"]
    send(fl, "gw-01", "profile_test", {"analyzer": "an-01", "address": 9999, "type": "f32"})
    assert rec.last(p.modem_topic("gw-01", "ack"))[1]["ok"] is False


def test_other_commands_still_work():
    fl, rec = make_fleet()
    send(fl, "gw-01", "ping", {})
    assert rec.last(p.modem_topic("gw-01", "ack"))[1]["ok"]
    send(fl, "gw-01", "profile_delete", {"id": "nope"})
    assert rec.last(p.modem_topic("gw-01", "ack"))[1]["ok"] is False
