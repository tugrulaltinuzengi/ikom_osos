package com.osos.hmi.console

import com.osos.hmi.AppContainer
import com.osos.hmi.alarms.AlarmRule
import com.osos.hmi.model.ALL_KEYS
import com.osos.hmi.model.BOUND_ACTIONS
import com.osos.hmi.model.BoundAction
import com.osos.hmi.model.DigitCommand
import com.osos.hmi.model.shortName
import org.json.JSONObject
import java.util.UUID

// Text front-end onto the same state the Alarms/Commands dialogs edit — the
// dialogs stay the guided path, this is the fast one. The device goes onto a
// voltage-meter matrix where the same band is entered per phase, so `V_*`
// expands over L1/L2/L3 instead of three near-identical dialog trips.
class ConsoleInterpreter(private val c: AppContainer) {

    // "clear" is the only command that touches history, hence the flag
    data class Result(val lines: List<String>, val clearScrollback: Boolean = false)

    // echo + result into the shared scrollback (what the screen calls)
    fun submit(input: String) {
        val text = input.trim()
        if (text.isEmpty()) return
        val r = run(text)
        c.consoleLines.value =
            if (r.clearScrollback) r.lines
            else (c.consoleLines.value + "> $text" + r.lines).takeLast(MAX_LINES)
    }

    fun run(input: String): Result {
        val tok = input.trim().split(WS)
        return when (tok[0].lowercase()) {
            "help" -> help(tok.getOrNull(1))
            "rule" -> rule(tok)
            "bind" -> bind(tok)
            "do" -> doAction(tok)
            "show" -> show(tok)
            "reset" -> reset(tok)
            "clear" -> Result(listOf(BANNER), clearScrollback = true)
            else -> err("unknown command '${tok[0]}' — type 'help'")
        }
    }

    // --- help ---

    private fun help(what: String?): Result {
        if (what == null) {
            return ok(
                DOCS.map { "${it.usage} — ${it.blurb}" } +
                    "✓ 'help <cmd>' for detail and an example"
            )
        }
        val doc = DOCS.find { it.name == what.lowercase() }
            ?: return err("no help for '$what' — ${DOCS.joinToString(", ") { it.name }}")
        return ok(listOf(doc.usage, "  ${doc.blurb}") + doc.detail.lines().map { "  $it" })
    }

    // --- rule ---

    private fun rule(tok: List<String>): Result {
        val rules = c.alarms.rules.value
        return when (val sub = tok.getOrNull(1)?.lowercase()) {
            null -> err("rule needs arguments — 'help rule'")
            "list" -> ok(listRules(rules))
            "rm" -> rmRule(tok, rules)
            "on", "off" -> toggleRule(tok, rules, sub == "on")
            else -> addRule(tok, rules)
        }
    }

    private fun addRule(tok: List<String>, rules: List<AlarmRule>): Result {
        val spec = tok[1]
        val keys = expandKeys(spec)
        if (keys.isEmpty()) return err("unknown key '$spec' — closest: ${suggest(spec)}")
        val min = tok.getOrNull(2)?.toDoubleOrNull()
            ?: return err("bad min '${tok.getOrNull(2).orEmpty()}' — 'rule V_L1 207 253'")
        val max = tok.getOrNull(3)?.toDoubleOrNull()
            ?: return err("bad max '${tok.getOrNull(3).orEmpty()}' — 'rule V_L1 207 253'")
        if (min > max) return err("min %.2f is above max %.2f".format(min, max))
        var hold = DEFAULT_HOLD
        if (tok.size > 4) {
            if (!tok[4].equals("hold", true)) return err("expected 'hold <s>' after max, got '${tok[4]}'")
            hold = tok.getOrNull(5)?.toIntOrNull()
                ?: return err("bad hold '${tok.getOrNull(5).orEmpty()}' — seconds, e.g. 'hold 30'")
            if (hold < 0) return err("hold must be ≥ 0")
        }
        // re-entering a key replaces its band: two live bands on one key would
        // just fire twice, and the matrix workflow is "type it again, better"
        val replaced = rules.count { it.key in keys }
        val added = keys.map { AlarmRule(UUID.randomUUID().toString(), it, min, max, hold, true) }
        c.alarms.setRules(rules.filterNot { it.key in keys } + added)
        return ok(
            listOf(
                "✓ %d rule(s) %s in [%.2f, %.2f] hold %ds%s".format(
                    added.size, keys.joinToString(", ") { shortName(it) },
                    min, max, hold, if (replaced > 0) " (replaced $replaced)" else "",
                )
            )
        )
    }

    private fun listRules(rules: List<AlarmRule>): List<String> {
        if (rules.isEmpty()) return listOf("✓ no rules — 'rule V_* 207 253' to start")
        return rules.mapIndexed { i, r ->
            "%2d  %-14s [%.2f, %.2f] hold %ds  %s".format(
                i + 1, shortName(r.key), r.min, r.max, r.holdSec, if (r.enabled) "on" else "off",
            )
        } + "✓ ${rules.size} rules"
    }

    private fun rmRule(tok: List<String>, rules: List<AlarmRule>): Result {
        val arg = tok.getOrNull(2) ?: return err("rule rm needs <n> or 'all'")
        if (arg.equals("all", true)) {
            c.alarms.setRules(emptyList())
            return ok(listOf("✓ removed ${rules.size} rules"))
        }
        val r = ruleAt(arg, rules) ?: return err(noSuchRule(arg, rules))
        c.alarms.setRules(rules.filterNot { it.id == r.id })
        return ok(listOf("✓ removed ${shortName(r.key)}"))
    }

    private fun toggleRule(tok: List<String>, rules: List<AlarmRule>, on: Boolean): Result {
        val arg = tok.getOrNull(2) ?: return err("rule ${if (on) "on" else "off"} needs <n>")
        val r = ruleAt(arg, rules) ?: return err(noSuchRule(arg, rules))
        c.alarms.setRules(rules.map { if (it.id == r.id) it.copy(enabled = on) else it })
        return ok(listOf("✓ ${shortName(r.key)} ${if (on) "enabled" else "disabled"}"))
    }

    private fun ruleAt(arg: String, rules: List<AlarmRule>): AlarmRule? =
        arg.toIntOrNull()?.let { rules.getOrNull(it - 1) }

    private fun noSuchRule(arg: String, rules: List<AlarmRule>) =
        "no rule #$arg — ${rules.size} rules, see 'rule list'"

    // --- bind ---

    private fun bind(tok: List<String>): Result {
        val map = c.digitMap.value
        return when (tok.getOrNull(1)?.lowercase()) {
            null -> err("bind needs arguments — 'help bind'")
            "list" -> ok(listBinds(map))
            "clear" -> {
                val d = digitOf(tok.getOrNull(2)) ?: return err("bad digit '${tok.getOrNull(2).orEmpty()}' — 0-9")
                c.setDigitBinds(map + (d to DigitCommand(d, "none", "unassigned", 0, "", "unassigned")))
                ok(listOf("✓ digit $d unbound"))
            }
            else -> {
                val d = digitOf(tok[1]) ?: return err("bad digit '${tok[1]}' — 0-9, or 'bind list'")
                val a = findAction(tok.getOrNull(2))
                    ?: return err("unknown action '${tok.getOrNull(2).orEmpty()}' — see 'show actions'")
                c.setDigitBinds(map + (d to a.toDigitCommand(d)))
                ok(listOf("✓ digit $d → ${a.label} (${a.scope})"))
            }
        }
    }

    private fun listBinds(map: Map<Int, DigitCommand>): List<String> =
        (0..9).map { d ->
            val cmd = map[d]
            if (cmd == null || cmd.scope == "none") "%d  %-24s %s".format(d, "—", "none")
            else "%d  %-24s %s".format(d, cmd.label, cmd.scope)
        } + "✓ ${map.values.count { it.scope != "none" }} digits bound"

    private fun digitOf(s: String?): Int? = s?.toIntOrNull()?.takeIf { it in 0..9 }

    // --- do / show / reset ---

    private fun doAction(tok: List<String>): Result {
        val a = findAction(tok.getOrNull(1))
            ?: return err("unknown action '${tok.getOrNull(1).orEmpty()}' — see 'show actions'")
        return if (a.scope == "local") {
            c.showMonitorView(a.page)
            c.uiTab.value = 0
            ok(listOf("✓ monitor → ${a.page}"))
        } else {
            val args = JSONObject()
            if (a.action == "set_interval") args.put("seconds", a.seconds)
            val mid = c.selectedMid()
                ?: return err("no analyzer selected — pick one in Monitor first")
            val id = c.client.publishCmd(mid, a.action, args)
            ok(listOf("✓ sent ${a.action} to $mid ($id) — waiting for ack"))
        }
    }

    private fun show(tok: List<String>): Result = when (tok.getOrNull(1)?.lowercase()) {
        "keys" -> ok(
            ALL_KEYS.map { "%-8s %s".format(aliasFor(it) ?: "", it) } +
                "✓ ${ALL_KEYS.size} keys · '_*' = L1 L2 L3, '_ALL' adds N"
        )
        "actions" -> ok(
            BOUND_ACTIONS.map { "%-9s %-24s %s".format(it.key, it.label, it.scope) } +
                "✓ ${BOUND_ACTIONS.size} actions — 'do <action>' or 'bind <digit> <action>'"
        )
        "status" -> ok(status())
        else -> err("show what? keys | actions | status")
    }

    private fun status(): List<String> {
        val t = c.selectedTelemetry()
        val s = c.selectedStatus()
        val f = c.fleet.value
        val sel = c.selected.value
        return listOf(
            "broker    ${if (c.client.connected.value) "connected" else "down"} · " +
                "${c.prefs.host}:${c.prefs.port}${if (c.prefs.tls) " tls" else ""}",
            "fleet     ${f.modems.size} modems · ${f.allAnalyzers.size} analyzers · " +
                "${f.modems.values.count { it.state?.sleep == true }} asleep",
            "selected  ${sel?.let { "${it.mid}/${it.aid}" } ?: "none"}",
            "gateway   ${s?.state ?: "?"}" +
                (s?.let { " · fw ${it.fw} · ${it.ip}" } ?: ""),
            "telemetry " + (t?.let {
                "seq ${it.seq} · ${it.ts} · " + if (it.meterOk) "meter ok" else "meter FAULT"
            } ?: "none yet"),
            "alarms    ${c.alarms.active.value.size} active · ${c.alarms.rules.value.size} rules",
            "✓ ${c.digitMap.value.values.count { it.scope != "none" }} digits bound",
        )
    }

    private fun reset(tok: List<String>): Result {
        if (!"defaults".equals(tok.getOrNull(1), true)) return err("only 'reset defaults' — 'help reset'")
        c.alarms.setRules(emptyList())
        DEFAULT_RULES.forEach { run(it) }   // same parser, so defaults can't drift
        c.resetDigitBinds()
        return ok(
            listOf(
                "✓ restored ${c.alarms.rules.value.size} rules " +
                    "(230 V ±10 %, 50 Hz ±1 %) + ${c.digitMap.value.values.count { it.scope != "none" }} binds"
            )
        )
    }

    private fun findAction(name: String?): BoundAction? =
        name?.let { n -> BOUND_ACTIONS.find { it.key.equals(n, true) } }

    private fun BoundAction.toDigitCommand(digit: Int) = DigitCommand(
        digit = digit,
        scope = scope,
        action = if (scope == "local") "view" else action,
        seconds = seconds,
        page = page,
        label = label,
    )

    private fun ok(lines: List<String>) = Result(lines)
    private fun err(reason: String) = Result(listOf("✗ $reason"))

    companion object {
        const val BANNER = "OSOS console — type 'help'. Example: rule V_* 207 253 hold 30"
        private const val MAX_LINES = 400
        private const val DEFAULT_HOLD = 30

        // EN 50160 / TEDAŞ LV band: 230 V ±10 %, 50 Hz ±1 %.
        private val DEFAULT_RULES = listOf(
            "rule V_* 207 253 hold 30",
            "rule F_L1 49.5 50.5 hold 10",
        )
    }
}

private val WS = Regex("\\s+")
private val PHASES = listOf("L1", "L2", "L3")

private data class Doc(val name: String, val usage: String, val blurb: String, val detail: String)

private val DOCS = listOf(
    Doc("help", "help [cmd]", "this list, or one command in detail", "help rule"),
    Doc(
        "rule", "rule <key> <min> <max> [hold <s>]", "add a value alarm (hold 30 s)",
        "rule V_* 207 253 hold 30   one rule per phase (L1 L2 L3)\n" +
            "rule list                  numbered, in engine order\n" +
            "rule rm <n|all>            remove\n" +
            "rule on <n> | rule off <n> enable / disable\n" +
            "<key>: alias (V_L1), full key, or a unique prefix.\n" +
            "'_*' = L1 L2 L3, '_ALL' = L1 L2 L3 N. Re-entering a key\n" +
            "replaces its band.",
    ),
    Doc(
        "bind", "bind <digit> <action>", "bind an MNIST digit 0-9 to an action",
        "bind 2 int2       digit 2 → fast reporting\n" +
            "bind list         the whole digit map\n" +
            "bind clear 2      unbind (scope 'none')",
    ),
    Doc("do", "do <action>", "run an action now", "do read_now\ndo viewL1"),
    Doc("show", "show keys|actions|status", "reference tables and link state", "show keys"),
    Doc("reset", "reset defaults", "restore built-in rules + digit binds", "reset defaults"),
    Doc("clear", "clear", "wipe the scrollback", "clear"),
)

// The operator types V_L1, not MainBus_Voltage_L1. Built from ALL_KEYS so a
// family without a neutral (F, PF, …) simply has no _N alias.
internal val KEY_ALIASES: Map<String, String> = buildMap {
    listOf(
        "V" to "Voltage", "I" to "Current", "F" to "Freq",
        "PF" to "PF", "COS" to "CosPhi", "TAN" to "TanPhi",
    ).forEach { (short, full) ->
        (PHASES + "N").forEach { ph ->
            val key = "MainBus_${full}_$ph"
            if (key in ALL_KEYS) put("${short}_$ph", key)
        }
    }
    put("TAN_TOT", "MainBus_TanPhi_Tot")
    put("VSUP", "Supply_Voltage")
    put("SUPPLY", "Supply_Voltage")
}

internal fun aliasFor(key: String): String? =
    KEY_ALIASES.entries.firstOrNull { it.value == key }?.key

// alias, full key, or an unambiguous prefix of either
internal fun resolveKey(token: String): String? {
    val t = token.uppercase()
    KEY_ALIASES[t]?.let { return it }
    ALL_KEYS.firstOrNull { it.equals(token, true) }?.let { return it }
    val hits = (
        KEY_ALIASES.filterKeys { it.startsWith(t) }.values +
            ALL_KEYS.filter { it.uppercase().startsWith(t) }
        ).distinct()
    return hits.singleOrNull()
}

// `V_*` = the three phases (the matrix case); `V_ALL` = phases + neutral.
internal fun expandKeys(spec: String): List<String> {
    val t = spec.uppercase()
    return when {
        "*" in t -> PHASES.mapNotNull { resolveKey(t.replace("*", it)) }.distinct()
        t.endsWith("_ALL") -> (PHASES + "N").mapNotNull { resolveKey(t.removeSuffix("ALL") + it) }.distinct()
        else -> listOfNotNull(resolveKey(t))
    }
}

// "closest valid aliases" = longest shared prefix, which is what a typo hits
internal fun suggest(token: String): String {
    val t = token.uppercase().substringBefore('*')
    return KEY_ALIASES.keys
        .sortedByDescending { commonPrefix(it, t) }
        .take(4)
        .joinToString(", ")
}

private fun commonPrefix(a: String, b: String): Int {
    var i = 0
    while (i < minOf(a.length, b.length) && a[i] == b[i]) i++
    return i
}
