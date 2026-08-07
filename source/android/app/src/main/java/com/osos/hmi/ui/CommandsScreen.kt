package com.osos.hmi.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import com.osos.hmi.AppContainer
import com.osos.hmi.csv.CsvExport
import com.osos.hmi.model.BOUND_ACTIONS
import com.osos.hmi.nn.Preprocess

// Custom-command management: the "learning dataset" flow collects 10-15
// drawings per symbol; saving retrains the on-device head automatically.
private const val SAMPLES_MIN = 10
private const val SAMPLES_MAX = 15

@Composable
fun CommandsScreen(c: AppContainer) {
    val rt by c.store.runtime.collectAsState()
    val rebuilding by c.store.rebuilding.collectAsState()
    val digits by c.digitMap.collectAsState()
    var adding by remember { mutableStateOf(false) }
    val ctx = LocalContext.current

    LazyColumn(
        Modifier
            .fillMaxWidth()
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item { Text("Digit commands (MNIST)", style = MaterialTheme.typography.titleSmall) }
        items(digits.values.sortedBy { it.digit }) { d ->
            Text(
                " ${d.digit}  ${d.label}  ·  ${d.scope}",
                style = MaterialTheme.typography.bodySmall,
                fontFamily = FontFamily.Monospace,
            )
        }

        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Custom commands", style = MaterialTheme.typography.titleSmall)
                Spacer(Modifier.weight(1f))
                if (rebuilding) CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
            }
        }
        item {
            val headText = if (rt.head != null) {
                "head: trained on ${rt.cmds.size} classes (${rt.trainedOn} augmented views)"
            } else {
                "head: needs ≥2 commands — cosine matching only"
            }
            Text(
                headText,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
            )
        }
        items(rt.cmds, key = { it.name }) { cmd ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(cmd.name, style = MaterialTheme.typography.titleSmall)
                        Spacer(Modifier.weight(1f))
                        TextButton(onClick = { c.store.remove(cmd.name) }) { Text("Delete") }
                    }
                    val action = BOUND_ACTIONS.find { it.key == cmd.actionKey }
                    Text(
                        "→ ${action?.label ?: cmd.actionKey} (${action?.scope ?: "?"}) · ${cmd.samples.size} samples",
                        style = MaterialTheme.typography.bodySmall,
                    )
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        items(cmd.samples) { s ->
                            Image(
                                bitmap = Preprocess.gridToBitmap(s).asImageBitmap(),
                                contentDescription = null,
                                modifier = Modifier.size(32.dp),
                            )
                        }
                    }
                }
            }
        }

        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(onClick = { adding = true }) { Text("✚ Add command") }
                OutlinedButton(
                    onClick = { CsvExport.exportAndShare(ctx, rt.cmds) },
                    enabled = rt.cmds.isNotEmpty(),
                ) { Text("Export CSV") }
            }
        }
        item {
            Text(
                "CSV format label,p0..p783 (labels 10+) — feeds phase-2 retraining " +
                    "of the full net on the PC (neural_net_c + export_weights.py).",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f),
            )
        }
    }

    if (adding) {
        AddCommandDialog(c, onClose = { adding = false })
    }
}

@Composable
private fun AddCommandDialog(c: AppContainer, onClose: () -> Unit) {
    var name by remember { mutableStateOf("") }
    var action by remember { mutableStateOf(BOUND_ACTIONS.first()) }
    var menuOpen by remember { mutableStateOf(false) }
    var clearSignal by remember { mutableIntStateOf(0) }
    val samples = remember { mutableStateListOf<IntArray>() }

    Dialog(onDismissRequest = onClose) {
        Surface(shape = MaterialTheme.shapes.large) {
            Column(
                Modifier
                    .padding(14.dp)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text("New custom command", style = MaterialTheme.typography.titleMedium)

                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text("name") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )

                Box {
                    OutlinedButton(onClick = { menuOpen = true }) {
                        Text("${action.label} (${action.scope})")
                    }
                    DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                        BOUND_ACTIONS.forEach { a ->
                            DropdownMenuItem(
                                text = { Text("${a.label} (${a.scope})") },
                                onClick = {
                                    action = a
                                    menuOpen = false
                                },
                            )
                        }
                    }
                }

                Text(
                    "Draw the same symbol ${SAMPLES_MIN}–${SAMPLES_MAX}× — " +
                        "${samples.size}/$SAMPLES_MAX collected" +
                        if (samples.size >= SAMPLES_MAX) " (full)" else "",
                    style = MaterialTheme.typography.labelMedium,
                )

                DrawPad(
                    modifier = Modifier.fillMaxWidth(),
                    clearSignal = clearSignal,
                    onGrid = { grid ->
                        if (samples.size < SAMPLES_MAX) samples.add(grid)
                        clearSignal++
                    },
                )

                LazyRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    items(samples.toList()) { s ->
                        Image(
                            bitmap = Preprocess.gridToBitmap(s).asImageBitmap(),
                            contentDescription = null,
                            modifier = Modifier.size(32.dp),
                        )
                    }
                }

                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedButton(
                        onClick = { samples.removeLastOrNull() },
                        enabled = samples.isNotEmpty(),
                    ) { Text("Undo") }
                    Button(
                        onClick = {
                            c.store.add(name.trim(), action.key, samples.toList())
                            onClose()
                        },
                        enabled = samples.size >= SAMPLES_MIN && name.isNotBlank(),
                    ) { Text("Save & train") }
                    TextButton(onClick = onClose) { Text("Cancel") }
                }
            }
        }
    }
}
