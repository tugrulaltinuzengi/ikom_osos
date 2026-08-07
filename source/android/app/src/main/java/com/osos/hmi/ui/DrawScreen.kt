package com.osos.hmi.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.osos.hmi.AppContainer
import com.osos.hmi.Recognizer
import com.osos.hmi.nn.Preprocess
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject

@Composable
fun DrawScreen(c: AppContainer) {
    var clearSignal by remember { mutableIntStateOf(0) }
    var outcome by remember { mutableStateOf<Recognizer.Outcome?>(null) }
    var pendingGw by remember { mutableStateOf<Recognizer.Decision.GatewayCmd?>(null) }
    var info by remember { mutableStateOf<String?>(null) }
    val banner by c.client.cmdBanner.collectAsState()
    val digits by c.digitMap.collectAsState()
    val scope = rememberCoroutineScope()

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        val cheat = digits.values
            .filter { it.scope != "none" }
            .sortedBy { it.digit }
            .joinToString(" · ") { "${it.digit} ${it.label}" }
        Text(
            cheat,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
        )

        DrawPad(
            modifier = Modifier.fillMaxWidth(),
            clearSignal = clearSignal,
            onPenDown = {
                pendingGw = null
                info = null
            },
            onGrid = { grid ->
                val out = c.recognizer.recognize(grid)
                outcome = out
                when (val d = out.decision) {
                    is Recognizer.Decision.LocalView -> {
                        c.showMonitorView(d.page)
                        info = "${d.source} → ${d.label}"
                        scope.launch {
                            delay(500)
                            clearSignal++
                            c.uiTab.value = 0
                        }
                    }
                    is Recognizer.Decision.GatewayCmd -> pendingGw = d
                    is Recognizer.Decision.Rejected -> info = d.reason
                }
            },
        )

        Row(
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedButton(onClick = {
                clearSignal++
                outcome = null
                pendingGw = null
                info = null
            }) { Text("Clear") }
            outcome?.let {
                Image(
                    bitmap = Preprocess.gridToBitmap(it.grid).asImageBitmap(),
                    contentDescription = "28x28 preview",
                    modifier = Modifier.size(56.dp),
                )
            }
            Spacer(Modifier.weight(1f))
        }

        // The safety gate: gateway commands go out only after an explicit tap
        // (recognition alone never publishes — same rule as the browser HMI).
        pendingGw?.let { d ->
            Card {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("${d.source} → ${d.label}", style = MaterialTheme.typography.titleSmall)
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Button(onClick = {
                            val args = JSONObject()
                            if (d.action == "set_interval") args.put("seconds", d.seconds)
                            // Commands go to the modem owning the selected
                            // analyzer. `load` is absent from BOUND_ACTIONS, so
                            // no drawn symbol can reach it (MX-3).
                            c.selectedMid()?.let { c.client.publishCmd(it, d.action, args) }
                            pendingGw = null
                            clearSignal++
                        }) { Text("Send") }
                        OutlinedButton(onClick = {
                            pendingGw = null
                            clearSignal++
                        }) { Text("Cancel") }
                    }
                }
            }
        }

        info?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
        banner?.let {
            Text(
                it,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.primary,
            )
        }

        outcome?.let { InspectorCard(it, c) }
    }
}

// "Let me see the embed classifiers": every recognition shows the digit
// softmax next to BOTH custom classifiers — trained-head probability and
// cosine similarity per class — so a match is never a black box.
@Composable
private fun InspectorCard(out: Recognizer.Outcome, c: AppContainer) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("Classifier inspector", style = MaterialTheme.typography.titleSmall)

            Text(
                "digits (MLP ${c.mlp.archLabel}, gate ≥ %.0f%%)".format(c.prefs.confMin * 100),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
            )
            out.digitTop3.forEach { (digit, p) ->
                Text(
                    "  %d  %5.1f%%  %s".format(digit, p * 100, bar(p)),
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                )
            }

            if (out.customRows.isNotEmpty()) {
                val mode = if (out.headUsed) {
                    "trained head (gate ≥ %.0f%% + cos ≥ 0.80)".format(c.prefs.headMin * 100)
                } else {
                    "cosine only (gate ≥ %.2f) — head needs ≥2 commands".format(c.prefs.simMin)
                }
                Text(
                    "custom symbols — $mode",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                )
                out.customRows.sortedByDescending { it.headProb ?: it.bestCos }.forEach { r ->
                    val head = r.headProb?.let { "head %5.1f%%".format(it * 100) } ?: "head    —"
                    Text(
                        "  %-10s %s  cos best %.3f avg %.3f".format(r.name.take(10), head, r.bestCos, r.avgCos),
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = FontFamily.Monospace,
                    )
                }
            }
        }
    }
}

private fun bar(p: Double): String = "█".repeat((p * 10).toInt().coerceIn(0, 10))
