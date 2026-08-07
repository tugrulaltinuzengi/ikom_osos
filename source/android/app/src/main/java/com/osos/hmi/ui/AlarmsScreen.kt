package com.osos.hmi.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import com.osos.hmi.AppContainer
import com.osos.hmi.alarms.AlarmRule
import com.osos.hmi.model.ALL_KEYS
import com.osos.hmi.model.shortName
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

private val timeFmt = SimpleDateFormat("HH:mm:ss", Locale.US)

@Composable
fun AlarmsScreen(c: AppContainer) {
    val active by c.alarms.active.collectAsState()
    val rules by c.alarms.rules.collectAsState()
    val logs by c.logEntries.collectAsState()
    var adding by remember { mutableStateOf(false) }

    LazyColumn(
        Modifier
            .fillMaxWidth()
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item { Text("Active alarms", style = MaterialTheme.typography.titleSmall) }
        if (active.isEmpty()) {
            item {
                Text(
                    "none",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f),
                )
            }
        }
        items(active, key = { it.id }) { a ->
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.error.copy(alpha = 0.18f),
                ),
            ) {
                Column(Modifier.padding(10.dp)) {
                    Text(a.message, style = MaterialTheme.typography.bodyMedium)
                    Text(
                        "since ${timeFmt.format(Date(a.since))}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                    )
                }
            }
        }

        item {
            Text(
                "Built-in: gateway offline (LWT / no telemetry) · meter fault ≥ 30 s.\n" +
                    "Value rules run on the telemetry stream — the DKM-440's Modbus read " +
                    "budget is fixed by the report interval, so no extra polling.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f),
            )
        }

        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Rules", style = MaterialTheme.typography.titleSmall)
                Spacer(Modifier.weight(1f))
                Button(onClick = { adding = true }) { Text("Add rule") }
            }
        }
        items(rules, key = { it.id }) { r ->
            Card(Modifier.fillMaxWidth()) {
                Row(
                    Modifier.padding(10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(
                            "${shortName(r.key)} in [%.2f, %.2f]".format(r.min, r.max),
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        Text(
                            "hold ${r.holdSec}s",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                        )
                    }
                    Switch(
                        checked = r.enabled,
                        onCheckedChange = { on ->
                            c.alarms.setRules(rules.map { if (it.id == r.id) it.copy(enabled = on) else it })
                        },
                    )
                    TextButton(onClick = { c.alarms.setRules(rules.filter { it.id != r.id }) }) {
                        Text("✕")
                    }
                }
            }
        }

        item { Text("Alarm history", style = MaterialTheme.typography.titleSmall) }
        items(logs.filter { it.source == "alarm" }.asReversed()) { e ->
            Text(
                "[${timeFmt.format(Date(e.time))}] ${e.text}",
                style = MaterialTheme.typography.bodySmall,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.75f),
            )
        }
    }

    if (adding) {
        AddRuleDialog(
            onSave = { key, min, max, hold ->
                c.alarms.setRules(
                    rules + AlarmRule(UUID.randomUUID().toString(), key, min, max, hold, true)
                )
                adding = false
            },
            onClose = { adding = false },
        )
    }
}

@Composable
private fun AddRuleDialog(onSave: (String, Double, Double, Int) -> Unit, onClose: () -> Unit) {
    var key by remember { mutableStateOf(ALL_KEYS.first()) }
    var menuOpen by remember { mutableStateOf(false) }
    var minText by remember { mutableStateOf("207") }
    var maxText by remember { mutableStateOf("253") }
    var holdText by remember { mutableStateOf("30") }

    Dialog(onDismissRequest = onClose) {
        Surface(shape = MaterialTheme.shapes.large) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("New alarm rule", style = MaterialTheme.typography.titleMedium)

                Box {
                    OutlinedButton(onClick = { menuOpen = true }) { Text(shortName(key)) }
                    DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                        ALL_KEYS.forEach { k ->
                            DropdownMenuItem(
                                text = { Text(shortName(k)) },
                                onClick = {
                                    key = k
                                    menuOpen = false
                                },
                            )
                        }
                    }
                }

                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = minText, onValueChange = { minText = it },
                        label = { Text("min") }, singleLine = true, modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = maxText, onValueChange = { maxText = it },
                        label = { Text("max") }, singleLine = true, modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = holdText, onValueChange = { holdText = it },
                        label = { Text("hold s") }, singleLine = true, modifier = Modifier.weight(1f),
                    )
                }

                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Button(
                        onClick = {
                            val mn = minText.toDoubleOrNull()
                            val mx = maxText.toDoubleOrNull()
                            val hold = holdText.toIntOrNull()
                            if (mn != null && mx != null && hold != null && mn <= mx && hold >= 0) {
                                onSave(key, mn, mx, hold)
                            }
                        },
                    ) { Text("Save") }
                    TextButton(onClick = onClose) { Text("Cancel") }
                }
            }
        }
    }
}
