package com.osos.hmi.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.osos.hmi.AppContainer
import org.json.JSONObject

@Composable
fun ModemDetailScreen(c: AppContainer, mid: String, onBack: () -> Unit) {
    val fleet by c.fleet.collectAsState()
    val modem = fleet.modems[mid]
    val asleep = modem?.state?.sleep == true
    var pending by remember { mutableStateOf<Pair<Int, Boolean>?>(null) }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp)
    ) {
        TextButton(onClick = onBack) { Text("< fleet") }
        Text(mid, style = MaterialTheme.typography.titleMedium)
        Text(
            modem?.status?.let { "${it.state} · fw ${it.fw} · ${it.ip} · ${it.rssi} dBm" }
                ?: "no status",
            style = MaterialTheme.typography.labelMedium,
        )

        if (modem?.unsupportedVersion == true) {
            Text(
                "This modem speaks a newer protocol than this app understands. " +
                    "Values may be incomplete.",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(vertical = 8.dp),
            )
        }

        Spacer(Modifier.height(16.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Sleep", style = MaterialTheme.typography.titleSmall)
            Spacer(Modifier.weight(1f))
            Text(
                modem?.state?.let { "interval ${it.interval}s" } ?: "",
                style = MaterialTheme.typography.labelSmall,
            )
            Spacer(Modifier.width(8.dp))
            Switch(
                checked = asleep,
                onCheckedChange = { on ->
                    c.client.publishCmd(mid, "sleep", JSONObject().put("on", on))
                },
            )
        }

        Spacer(Modifier.height(16.dp))
        Text("Load channels", style = MaterialTheme.typography.titleSmall)
        val loads = modem?.state?.loads.orEmpty()
        val channels = modem?.loadChannels ?: 0
        if (channels == 0) {
            Text("modem reports no load channels", style = MaterialTheme.typography.labelSmall)
        }
        for (ch in 1..channels) {
            // Rendered from what the modem REPORTS, never from what was just
            // requested: a failed command must not show as applied.
            val on = loads.getOrNull(ch - 1) == true
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("ch$ch", style = MaterialTheme.typography.bodyMedium)
                Spacer(Modifier.weight(1f))
                Text(
                    if (on) "ON" else "off",
                    style = MaterialTheme.typography.labelMedium,
                    color = if (on) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                )
                Spacer(Modifier.width(12.dp))
                OutlinedButton(onClick = { pending = ch to !on }) {
                    Text(if (on) "switch off" else "switch on")
                }
            }
        }
    }

    // Typed confirmation, not a yes/no dialog: this closes a contactor, and it
    // is deliberately reachable only from here - `load` is absent from
    // BOUND_ACTIONS so no drawn symbol can ever trigger it (MX-3).
    pending?.let { (ch, on) ->
        val phrase = "ch$ch ${if (on) "ON" else "OFF"}"
        var typed by remember(ch, on) { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { pending = null },
            title = { Text("Confirm load switch") },
            text = {
                Column {
                    Text("Type exactly:  $phrase")
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(typed, { typed = it }, singleLine = true)
                }
            },
            confirmButton = {
                TextButton(
                    enabled = typed == phrase,
                    onClick = {
                        c.client.publishCmd(
                            mid, "load",
                            JSONObject().put("ch", ch).put("on", on),
                        )
                        pending = null
                    },
                ) { Text("Switch") }
            },
            dismissButton = { TextButton(onClick = { pending = null }) { Text("Cancel") } },
        )
    }
}
