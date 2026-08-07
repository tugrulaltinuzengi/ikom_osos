package com.osos.hmi

import com.osos.hmi.data.CustomCommandStore
import com.osos.hmi.data.Prefs
import com.osos.hmi.model.BOUND_ACTIONS
import com.osos.hmi.model.BoundAction
import com.osos.hmi.model.DigitCommand
import com.osos.hmi.nn.Mlp
import com.osos.hmi.nn.Preprocess
import kotlinx.coroutines.flow.StateFlow

// Dispatch order mirrors www/hmi.js Pad.setOnDone: custom symbols first,
// digits second — but the custom decision uses the on-device trained head
// when available (>= 2 commands), with cosine as sanity gate and fallback.
class Recognizer(
    private val mlp: Mlp,
    private val store: CustomCommandStore,
    private val prefs: Prefs,
    // a flow, not a snapshot: console `bind` must affect the very next draw
    private val digitMap: StateFlow<Map<Int, DigitCommand>>,
) {
    // Everything the classifier inspector wants to show, per custom class.
    data class CustomRow(
        val name: String,
        val actionKey: String,
        val headProb: Double?,   // null when the head isn't trained
        val bestCos: Double,
        val avgCos: Double,
    )

    sealed class Decision {
        data class GatewayCmd(val label: String, val action: String, val seconds: Int, val source: String) : Decision()
        data class LocalView(val label: String, val page: String, val source: String) : Decision()
        data class Rejected(val reason: String) : Decision()
    }

    data class Outcome(
        val grid: IntArray,
        val digitPred: Int,
        val digitConf: Double,
        val digitTop3: List<Pair<Int, Double>>,
        val customRows: List<CustomRow>,
        val headUsed: Boolean,
        val decision: Decision,
    )

    fun recognize(grid: IntArray): Outcome {
        val x = Preprocess.toInput(grid)
        val rt = store.runtime.value

        // --- custom classifiers (both, for the inspector) ---
        val embed = if (rt.cmds.isNotEmpty()) mlp.embed(x) else null
        val headProbs = if (embed != null && rt.head != null) rt.head.predict(embed) else null
        val rows = rt.cmds.mapIndexed { ci, cmd ->
            val cosines = rt.embeds[ci].map { Mlp.cosine(embed!!, it) }
            CustomRow(
                name = cmd.name,
                actionKey = cmd.actionKey,
                headProb = headProbs?.get(ci),
                bestCos = cosines.maxOrNull() ?: 0.0,
                avgCos = if (cosines.isEmpty()) 0.0 else cosines.average(),
            )
        }

        // --- digit path ---
        val digit = mlp.forward(x)
        val top3 = digit.probs.withIndex()
            .sortedByDescending { it.value }
            .take(3)
            .map { it.index to it.value }

        // --- decision ---
        val headUsed = headProbs != null
        val customPick: CustomRow? = if (rows.isEmpty()) null else {
            if (headUsed) {
                val best = rows.maxByOrNull { it.headProb!! }!!
                // head confidence + cosine sanity: a confident head vote on an
                // embedding far from every stored sample is still rejected
                if (best.headProb!! >= prefs.headMin && best.bestCos >= 0.80) best else null
            } else {
                val best = rows.maxByOrNull { it.bestCos }!!
                if (best.bestCos >= prefs.simMin) best else null
            }
        }

        val decision: Decision = if (customPick != null) {
            val act = BOUND_ACTIONS.first { it.key == customPick.actionKey }
            toDecision(act, "custom \"${customPick.name}\"")
        } else if (digit.conf >= prefs.confMin) {
            val cmd = digitMap.value[digit.pred]
            if (cmd == null || cmd.scope == "none") {
                Decision.Rejected("digit ${digit.pred} is unassigned")
            } else if (cmd.scope == "local") {
                Decision.LocalView(cmd.label, cmd.page, "digit ${digit.pred}")
            } else {
                Decision.GatewayCmd(cmd.label, cmd.action, cmd.seconds, "digit ${digit.pred}")
            }
        } else {
            Decision.Rejected(
                "not sure — digit ${digit.pred} at %.0f%% (< %.0f%%)"
                    .format(digit.conf * 100, prefs.confMin * 100)
            )
        }

        return Outcome(grid, digit.pred, digit.conf, top3, rows, headUsed, decision)
    }

    private fun toDecision(act: BoundAction, source: String): Decision =
        if (act.scope == "local") {
            Decision.LocalView(act.label, act.page, source)
        } else {
            Decision.GatewayCmd(act.label, act.action, act.seconds, source)
        }
}
