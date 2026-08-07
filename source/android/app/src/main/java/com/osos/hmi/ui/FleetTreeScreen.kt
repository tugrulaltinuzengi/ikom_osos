package com.osos.hmi.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FloatingActionButton
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.osos.hmi.AppContainer
import com.osos.hmi.data.AnalyzerEntry
import com.osos.hmi.data.FleetRow
import com.osos.hmi.data.HealthBadge
import com.osos.hmi.data.UNFILED_FOLDER
import com.osos.hmi.data.flattenFleet
import com.osos.hmi.model.AnalyzerKey
import org.json.JSONObject

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun FleetTreeScreen(
    c: AppContainer,
    onModem: (String) -> Unit,
    onAnalyzer: (AnalyzerKey) -> Unit,
) {
    val fleet by c.fleet.collectAsState()
    val tree by c.tree.tree.collectAsState()
    var query by remember { mutableStateOf("") }
    var expanded by remember { mutableStateOf(setOf(UNFILED_FOLDER)) }
    var selected by remember { mutableStateOf<Set<AnalyzerKey>>(emptySet()) }
    var addMenu by remember { mutableStateOf(false) }
    var newFolder by remember { mutableStateOf<String?>(null) }
    var renameFolder by remember { mutableStateOf<String?>(null) }
    var moveFolder by remember { mutableStateOf<String?>(null) }
    var deleteFolder by remember { mutableStateOf<String?>(null) }
    var editing by remember { mutableStateOf<AnalyzerEntry?>(null) }
    var bulkMove by remember { mutableStateOf(false) }
    var provisioning by remember { mutableStateOf(false) }
    var adopting by remember { mutableStateOf(false) }

    val rows = flattenFleet(fleet, tree, query, expanded)

    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize()) {
            MasterSleepRow(c)
            WakeDigestBanner(c)
            OutlinedTextField(
                value = query,
                onValueChange = { query = it },
                label = { Text("search fleet") },
                singleLine = true,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 4.dp),
            )
            if (selected.isNotEmpty()) {
                SelectionBar(
                    count = selected.size,
                    onMove = { bulkMove = true },
                    onSleep = { on ->
                        selected.map { it.mid }.distinct().forEach { mid ->
                            c.client.publishCmd(mid, "sleep", JSONObject().put("on", on))
                        }
                    },
                    onUnfile = {
                        selected.forEach { who ->
                            fleet.analyzer(who.mid, who.aid)?.let { a ->
                                c.tree.assign(a.mid, a.aid, a.name, "", fleet)
                            }
                        }
                        selected = emptySet()
                    },
                    onClear = { selected = emptySet() },
                )
            }
            LazyColumn(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                items(rows, key = { it.key }) { row ->
                    when (row) {
                        is FleetRow.Folder -> FolderRow(
                            row = row,
                            onToggle = {
                                expanded = if (row.path in expanded) expanded - row.path else expanded + row.path
                            },
                            onRename = { renameFolder = row.path },
                            onMove = { moveFolder = row.path },
                            onDelete = { deleteFolder = row.path },
                        )
                        is FleetRow.Modem -> ModemOutlineRow(
                            row = row,
                            onOpen = { onModem(row.mid) },
                            onToggle = {
                                expanded = if (row.key in expanded) expanded - row.key else expanded + row.key
                            },
                            onSleep = { on -> c.client.publishCmd(row.mid, "sleep", JSONObject().put("on", on)) },
                        )
                        is FleetRow.Analyzer -> {
                            val isSelected = row.who in selected
                            AnalyzerOutlineRow(
                                row = row,
                                selected = isSelected,
                                onClick = {
                                    if (selected.isNotEmpty()) {
                                        selected = if (isSelected) selected - row.who else selected + row.who
                                    } else onAnalyzer(row.who)
                                },
                                onLongClick = {
                                    selected = if (isSelected) selected - row.who else selected + row.who
                                },
                                onEdit = { editing = fleet.analyzer(row.who.mid, row.who.aid) },
                            )
                        }
                    }
                }
                item { Spacer(Modifier.height(72.dp)) }
            }
        }

        Box(Modifier.align(Alignment.BottomEnd).padding(18.dp)) {
            FloatingActionButton(onClick = { addMenu = true }) { Text("+") }
            DropdownMenu(expanded = addMenu, onDismissRequest = { addMenu = false }) {
                DropdownMenuItem(text = { Text("Folder") }, onClick = { addMenu = false; newFolder = "" })
                DropdownMenuItem(text = { Text("Meter") }, onClick = { addMenu = false; provisioning = true })
                DropdownMenuItem(text = { Text("Adopt unfiled") }, onClick = { addMenu = false; adopting = true })
            }
        }
    }

    newFolder?.let { current ->
        TextPrompt("New folder", current, { newFolder = null }) {
            c.tree.createFolder(it)
            expanded = expanded + it
            newFolder = null
        }
    }
    renameFolder?.let { path ->
        TextPrompt("Rename folder", path, { renameFolder = null }) {
            c.tree.renameFolder(path, it, fleet)
            expanded = expanded - path + it
            renameFolder = null
        }
    }
    moveFolder?.let { path ->
        TextPrompt("Move folder under", "", { moveFolder = null }) {
            c.tree.moveFolder(path, it, fleet)
            moveFolder = null
        }
    }
    deleteFolder?.let { path ->
        AlertDialog(
            onDismissRequest = { deleteFolder = null },
            title = { Text("Delete folder") },
            text = { Text("Meters in this folder will move to Unfiled.") },
            confirmButton = {
                TextButton(onClick = { c.tree.deleteFolder(path, fleet); deleteFolder = null }) {
                    Text("Delete")
                }
            },
            dismissButton = { TextButton(onClick = { deleteFolder = null }) { Text("Cancel") } },
        )
    }
    bulkMove.takeIf { it }?.let {
        TextPrompt("Move selected to", "", { bulkMove = false }) { folder ->
            selected.forEach { who ->
                fleet.analyzer(who.mid, who.aid)?.let { a -> c.tree.assign(a.mid, a.aid, a.name, folder, fleet) }
            }
            selected = emptySet()
            bulkMove = false
        }
    }
    editing?.let { a ->
        RenameDialog(
            a = a,
            onDismiss = { editing = null },
            onConfirm = { name, folder ->
                c.tree.assign(a.mid, a.aid, name, folder, fleet)
                editing = null
            },
        )
    }
    if (provisioning) ProvisioningDialog(onDismiss = { provisioning = false })
    if (adopting) AdoptDialog(c, onDismiss = { adopting = false })
}

@Composable
private fun SelectionBar(
    count: Int,
    onMove: () -> Unit,
    onSleep: (Boolean) -> Unit,
    onUnfile: () -> Unit,
    onClear: () -> Unit,
) {
    Card(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp)) {
        Row(Modifier.padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("$count selected", style = MaterialTheme.typography.titleSmall)
            Spacer(Modifier.weight(1f))
            TextButton(onClick = onMove) { Text("Move") }
            TextButton(onClick = { onSleep(true) }) { Text("Sleep") }
            TextButton(onClick = { onSleep(false) }) { Text("Wake") }
            TextButton(onClick = onUnfile) { Text("Unfile") }
            TextButton(onClick = onClear) { Text("Clear") }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun FolderRow(
    row: FleetRow.Folder,
    onToggle: () -> Unit,
    onRename: () -> Unit,
    onMove: () -> Unit,
    onDelete: () -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(start = (row.depth * 14).dp, top = 8.dp)
            .combinedClickable(onClick = onToggle),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(if (row.expanded) "v" else ">", style = MaterialTheme.typography.labelMedium)
        Spacer(Modifier.width(8.dp))
        Text(row.name, style = MaterialTheme.typography.titleSmall)
        Spacer(Modifier.width(8.dp))
        Text("${row.meterCount}", style = MaterialTheme.typography.labelSmall)
        HealthText(row.badge)
        Spacer(Modifier.weight(1f))
        TextButton(onClick = onRename) { Text("rename") }
        TextButton(onClick = onMove) { Text("move") }
        TextButton(onClick = onDelete) { Text("del") }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ModemOutlineRow(
    row: FleetRow.Modem,
    onOpen: () -> Unit,
    onToggle: () -> Unit,
    onSleep: (Boolean) -> Unit,
) {
    Card(Modifier.fillMaxWidth().padding(start = (row.depth * 14).dp)) {
        Row(
            Modifier
                .fillMaxWidth()
                .combinedClickable(onClick = onOpen, onLongClick = onToggle)
                .padding(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(row.mid, style = MaterialTheme.typography.bodyMedium)
                    Spacer(Modifier.width(8.dp))
                    if (row.legacy) Text("v1", style = MaterialTheme.typography.labelSmall)
                    HealthText(row.badge)
                }
                Text(
                    listOfNotNull(
                        if (row.online) "online" else "offline",
                        if (row.asleep) "asleep" else "awake",
                        row.interval.takeIf { it > 0 }?.let { "${it}s" },
                        row.loads.takeIf { it.isNotEmpty() }?.mapIndexed { i, on -> "L${i + 1}:${if (on) "on" else "off"}" }?.joinToString(" "),
                        "${row.analyzerCount} meters",
                    ).joinToString(" / "),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.65f),
                )
            }
            OutlinedButton(onClick = onToggle) { Text("meters") }
            Spacer(Modifier.width(8.dp))
            Switch(checked = row.asleep, onCheckedChange = onSleep)
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun AnalyzerOutlineRow(
    row: FleetRow.Analyzer,
    selected: Boolean,
    onClick: () -> Unit,
    onLongClick: () -> Unit,
    onEdit: () -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(start = (row.depth * 14).dp)
            .combinedClickable(onClick = onClick, onLongClick = onLongClick)
            .padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (selected) Checkbox(checked = true, onCheckedChange = { onLongClick() })
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(row.name, style = MaterialTheme.typography.bodyMedium)
                HealthText(row.badge)
            }
            Text("${row.who.mid} / ${row.who.aid}", style = MaterialTheme.typography.labelSmall)
        }
        // Dim, not error red: telemetry is only subscribed for the selected /
        // open modem, so "no value" here usually means "not watching this one".
        // Health is the badge's job.
        Text(
            row.voltageL1?.let { "%.1f V".format(it) } ?: "-",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurface
                .copy(alpha = if (row.voltageL1 == null) 0.35f else 0.7f),
        )
        TextButton(onClick = onEdit) { Text("edit") }
    }
}

@Composable
private fun HealthText(badge: HealthBadge) {
    val color = when (badge) {
        HealthBadge.OK -> Color(0xFF66BB6A)
        HealthBadge.WARN -> Color(0xFFFFA726)
        HealthBadge.DOWN -> MaterialTheme.colorScheme.error
        HealthBadge.UNKNOWN -> MaterialTheme.colorScheme.onSurface.copy(alpha = 0.45f)
    }
    Text("  ${badge.name.lowercase()}", style = MaterialTheme.typography.labelSmall, color = color)
}

@Composable
private fun MasterSleepRow(c: AppContainer) {
    val fleet by c.fleet.collectAsState()
    val mids = fleet.modems.filter { it.value.protocolVersion >= 2 }.keys
    val allAsleep = mids.isNotEmpty() && mids.all { fleet.modems[it]?.state?.sleep == true }
    Row(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("Master sleep", style = MaterialTheme.typography.titleSmall)
        Spacer(Modifier.weight(1f))
        Switch(
            checked = allAsleep,
            onCheckedChange = { on ->
                mids.forEach { mid -> c.client.publishCmd(mid, "sleep", JSONObject().put("on", on)) }
            },
        )
    }
}

@Composable
private fun WakeDigestBanner(c: AppContainer) {
    val digest by c.alarms.wakeDigest.collectAsState()
    if (digest.isEmpty()) return
    Card(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 4.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "While asleep - ${digest.size} alarm${if (digest.size == 1) "" else "s"}",
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onErrorContainer,
                )
                Spacer(Modifier.weight(1f))
                TextButton(onClick = { c.alarms.wakeDigest.value = emptyList() }) { Text("Dismiss") }
            }
            digest.forEach {
                Text(
                    "- ${it.message}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onErrorContainer,
                )
            }
        }
    }
}

@Composable
private fun TextPrompt(
    title: String,
    initial: String,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit,
) {
    var text by remember { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { OutlinedTextField(text, { text = it }, singleLine = true) },
        confirmButton = { TextButton(onClick = { onConfirm(text) }) { Text("OK") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun RenameDialog(
    a: AnalyzerEntry,
    onDismiss: () -> Unit,
    onConfirm: (String, String) -> Unit,
) {
    var name by remember { mutableStateOf(a.name) }
    var folder by remember { mutableStateOf(a.folder) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(a.aid) },
        text = {
            Column {
                OutlinedTextField(name, { name = it }, label = { Text("name") }, singleLine = true)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(folder, { folder = it }, label = { Text("folder") }, singleLine = true)
            }
        },
        confirmButton = { TextButton(onClick = { onConfirm(name, folder) }) { Text("Save") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun ProvisioningDialog(onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add meter") },
        text = {
            Text(
                "A modem can only provision meters when its firmware advertises that capability. " +
                    "The current protocol exposes registry truth but no provisioning endpoint, so add " +
                    "the analyzer in CFG_ANALYZERS and reflash the modem; it will appear here automatically.",
            )
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("OK") } },
    )
}

@Composable
private fun AdoptDialog(c: AppContainer, onDismiss: () -> Unit) {
    val fleet by c.fleet.collectAsState()
    val unfiled = fleet.allAnalyzers.filter { it.folder.isEmpty() }
    var filing by remember { mutableStateOf<AnalyzerEntry?>(null) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Adopt unfiled") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                if (unfiled.isEmpty()) Text("No unfiled meters are waiting.")
                unfiled.forEach { a ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("${a.mid} / ${a.aid}", modifier = Modifier.weight(1f))
                        TextButton(onClick = { filing = a }) { Text("file") }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Done") } },
    )
    filing?.let { a ->
        TextPrompt("File ${a.aid} under", "", { filing = null }) { folder ->
            c.tree.assign(a.mid, a.aid, a.name, folder, fleet)
            filing = null
            onDismiss()
        }
    }
}