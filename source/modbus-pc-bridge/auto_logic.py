"""Portable automation logic — the "brain" of the demo.

This is the `read -> decode -> DECIDE -> act` middle step. It is deliberately
*pure*: it takes a dict of decoded values and returns a Decision. No serial, no
network, no print. That is what makes it portable — the identical rules move onto
the ESP32 in Stage 1, where `act` flips a relay GPIO instead of printing.

The rules below mirror the DKM-440's own protection concepts (430_KUL.pdf p.28:
low/high voltage alarm, frequency alarm) so the demo behaves like İKOM's product.

Hysteresis + debounce are what stop a relay from chattering when a value hovers
right at the limit: we trip immediately on a clear violation but only restore
after the value has been comfortably back in range for `RESTORE_SAMPLES` polls.
"""

from dataclasses import dataclass, field

# --- limits (edit for your demo source) -------------------------------------
V_MIN = 200.0          # volts: below this = under-voltage fault
V_MAX = 250.0          # volts: above this = over-voltage fault
V_HYST = 5.0           # volts of clearance needed before restoring
FREQ_MIN = 49.0        # Hz
FREQ_MAX = 51.0        # Hz
RESTORE_SAMPLES = 3    # consecutive healthy polls required to re-close the relay


@dataclass
class Decision:
    state: str                       # "OK" or "FAULT: <reason>"
    relay_closed: bool               # desired relay state (True = load energised)
    action: str = ""                 # "TRIP" / "RESTORE" / "" (only on a change)
    faults: list = field(default_factory=list)


class Controller:
    """Holds the small amount of state needed for hysteresis/debounce."""

    def __init__(self):
        self.relay_closed = True     # start with the load energised
        self._healthy_streak = 0

    def _faults(self, v: dict) -> list:
        f = []
        for name in ("vL1", "vL2", "vL3"):
            if name in v:
                if v[name] < V_MIN:
                    f.append(f"undervoltage {name} ({v[name]}V)")
                elif v[name] > V_MAX:
                    f.append(f"overvoltage {name} ({v[name]}V)")
        if "freq" in v and v["freq"] > 0:   # ignore 0 (missing) readings
            if v["freq"] < FREQ_MIN or v["freq"] > FREQ_MAX:
                f.append(f"frequency {v['freq']}Hz")
        return f

    def _healthy_with_clearance(self, v: dict) -> bool:
        """True only when every value is back inside the limits PLUS hysteresis."""
        for name in ("vL1", "vL2", "vL3"):
            if name in v and not (V_MIN + V_HYST <= v[name] <= V_MAX - V_HYST):
                return False
        if "freq" in v and v["freq"] > 0 and not (FREQ_MIN <= v["freq"] <= FREQ_MAX):
            return False
        return True

    def decide(self, values: dict) -> Decision:
        faults = self._faults(values)
        action = ""

        if faults:
            self._healthy_streak = 0
            if self.relay_closed:
                self.relay_closed = False
                action = "TRIP"
            return Decision(state="FAULT: " + "; ".join(faults),
                            relay_closed=False, action=action, faults=faults)

        # No active fault. Count healthy polls toward restoring the relay.
        if self._healthy_with_clearance(values):
            self._healthy_streak += 1
        else:
            self._healthy_streak = 0

        if not self.relay_closed and self._healthy_streak >= RESTORE_SAMPLES:
            self.relay_closed = True
            action = "RESTORE"

        return Decision(state="OK", relay_closed=self.relay_closed, action=action)


if __name__ == "__main__":
    # Tiny self-test so you can see the state machine without any hardware.
    c = Controller()
    script = [
        {"vL1": 230, "vL2": 231, "vL3": 229, "freq": 50.0},   # OK
        {"vL1": 180, "vL2": 231, "vL3": 229, "freq": 50.0},   # under-voltage -> TRIP
        {"vL1": 230, "vL2": 231, "vL3": 229, "freq": 50.0},   # healthy 1
        {"vL1": 230, "vL2": 231, "vL3": 229, "freq": 50.0},   # healthy 2
        {"vL1": 230, "vL2": 231, "vL3": 229, "freq": 50.0},   # healthy 3 -> RESTORE
    ]
    for i, s in enumerate(script):
        d = c.decide(s)
        print(f"step {i}: {s} -> {d.state} relay={'CLOSED' if d.relay_closed else 'OPEN'}"
              f"{'  [' + d.action + ']' if d.action else ''}")
