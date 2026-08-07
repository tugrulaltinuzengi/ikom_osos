"""OSOS MQTT protocol v2 - constants and topic grammar.

Single source of truth for the Python side. The Kotlin counterpart is
android/.../mqtt/TopicRouter.kt and the firmware counterpart is
firmware8266/osos_gw8266/commands.h - all three must agree.

Topic grammar:
    osos/m/{mid}/{status|registry|state|event|cmd|ack|labels}
    osos/m/{mid}/a/{aid}/{telemetry|status}
    osos/tree
    osos/{gwId}/{telemetry|status|event|ack}      <- legacy v1, gwId != "m"

"m" and "a" are reserved positional segments. That is what keeps the v2 tree
from colliding with the v1 topics the shipping firmware still publishes.
"""

PROTO_V = 2

ROOT = "osos"
MODEM_SEG = "m"
ANALYZER_SEG = "a"

MODEM_LEAVES = frozenset(
    {"status", "registry", "state", "event", "cmd", "ack", "labels"}
)
ANALYZER_LEAVES = frozenset({"telemetry", "status"})
LEGACY_LEAVES = frozenset({"telemetry", "status", "event", "ack", "cmd"})

TREE_TOPIC = f"{ROOT}/tree"


def modem_topic(mid, leaf):
    if leaf not in MODEM_LEAVES:
        raise ValueError(f"not a modem leaf: {leaf}")
    return f"{ROOT}/{MODEM_SEG}/{mid}/{leaf}"


def analyzer_topic(mid, aid, leaf):
    if leaf not in ANALYZER_LEAVES:
        raise ValueError(f"not an analyzer leaf: {leaf}")
    return f"{ROOT}/{MODEM_SEG}/{mid}/{ANALYZER_SEG}/{aid}/{leaf}"


def parse(topic):
    """-> (kind, mid_or_gw, aid, leaf). kind in
    {modem, analyzer, tree, legacy, unknown}."""
    parts = topic.split("/")
    if not parts or parts[0] != ROOT:
        return ("unknown", None, None, None)

    if len(parts) == 2 and parts[1] == "tree":
        return ("tree", None, None, "tree")

    if len(parts) == 4 and parts[1] == MODEM_SEG and parts[3] in MODEM_LEAVES:
        return ("modem", parts[2], None, parts[3])

    if (
        len(parts) == 6
        and parts[1] == MODEM_SEG
        and parts[3] == ANALYZER_SEG
        and parts[5] in ANALYZER_LEAVES
    ):
        return ("analyzer", parts[2], parts[4], parts[5])

    # Legacy v1. The reserved segment check is what stops osos/m/telemetry
    # being mistaken for a gateway literally named "m".
    if len(parts) == 3 and parts[1] != MODEM_SEG and parts[2] in LEGACY_LEAVES:
        return ("legacy", parts[1], None, parts[2])

    return ("unknown", None, None, None)
