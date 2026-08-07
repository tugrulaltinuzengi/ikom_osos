package com.osos.hmi.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Tab
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
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.osos.hmi.AppContainer
import com.osos.hmi.data.TelemetryHistory
import com.osos.hmi.model.AnalyzerKey
import com.osos.hmi.model.MonitorLevel
import com.osos.hmi.model.VIEWS
import com.osos.hmi.model.shortName
import com.osos.hmi.model.unitFor
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private val timeFmt = SimpleDateFormat("HH:mm:ss", Locale.US)

// A pure renderer over AppContainer state. Navigation lives in the container
// because the subscription policy is derived from it: held here, every tab
// switch would destroy it and take the telemetry subscription with it.
@Composable
fun MonitorScreen(c: AppContainer) {
    val level by c.monitorLevel.collectAsState()
    when (val l = level) {
        is MonitorLevel.Tree ->
            FleetTreeScreen(
                c,
                onModem = { c.openMonitorModem(it) },
                onAnalyzer = { c.openMonitorAnalyzer(it) },
            )
        is MonitorLevel.Modem ->
            ModemDetailScreen(c, l.mid, onBack = { c.closeMonitorDetail() })
        is MonitorLevel.Analyzer ->
            AnalyzerDetailScreen(c, l.who, onBack = { c.closeMonitorDetail() })
    }
}

@Composable
fun AnalyzerDetailScreen(c: AppContainer, who: AnalyzerKey, onBack: () -> Unit) {
    val fleet by c.fleet.collectAsState()
    val t = fleet.analyzer(who.mid, who.aid)?.latest
    val view by c.uiMonitorView.collectAsState()
    val historyVersion by c.history.version.collectAsState()
    val logs by c.logEntries.collectAsState()
    var sparkKey by remember { mutableStateOf<String?>(null) }

    Column(Modifier.fillMaxSize()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onBack) { Text("< fleet") }
            Text(
                fleet.analyzer(who.mid, who.aid)?.name ?: who.aid,
                style = MaterialTheme.typography.titleSmall,
            )
        }
        val meta = t?.let {
            "seq ${it.seq} · ${it.ts} · " +
                (if (it.meterOk) "meter ok" else "meter FAULT") +
                (if (it.buffered) " · backfill" else "")
        } ?: "no telemetry yet"
        Text(
            meta,
            style = MaterialTheme.typography.labelMedium,
            color = if (t?.meterOk == false) MaterialTheme.colorScheme.error
            else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
        )

        // Scrollable, not fixed: a fixed row splits ~344 dp across five tabs
        // and "overview" breaks mid-word. Here every label keeps one line and
        // the row scrolls to whichever tab is selected (draw pad included).
        val viewKeys = VIEWS.keys.toList()
        ScrollableTabRow(
            selectedTabIndex = viewKeys.indexOf(view).coerceAtLeast(0),
            edgePadding = 8.dp,
        ) {
            viewKeys.forEach { k ->
                Tab(
                    selected = view == k,
                    onClick = { c.uiMonitorView.value = k },
                    text = {
                        Text(
                            k,
                            style = MaterialTheme.typography.labelLarge,
                            maxLines = 1,
                            softWrap = false,
                        )
                    },
                )
            }
        }

        LazyColumn(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            item { Spacer(Modifier.height(2.dp)) }
            items(VIEWS[view].orEmpty().chunked(2)) { pair ->
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    pair.forEach { key ->
                        Tile(
                            key = key,
                            value = t?.values?.get(key),
                            selected = sparkKey == key,
                            modifier = Modifier
                                .weight(1f)
                                .clickable { sparkKey = if (sparkKey == key) null else key },
                        )
                    }
                    if (pair.size == 1) Spacer(Modifier.weight(1f))
                }
            }
            sparkKey?.let { key ->
                item { SparklineCard(who, key, c.history, historyVersion) }
            }
            item {
                Text(
                    "Log",
                    style = MaterialTheme.typography.titleSmall,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }
            items(logs.asReversed()) { e ->
                Text(
                    "[${timeFmt.format(Date(e.time))}] ${e.source}: ${e.text}",
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.75f),
                )
            }
            item { Spacer(Modifier.height(8.dp)) }
        }
    }
}

@Composable
private fun Tile(key: String, value: Double?, selected: Boolean, modifier: Modifier = Modifier) {
    Card(modifier) {
        Column(Modifier.padding(10.dp)) {
            Text(
                shortName(key),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
            )
            Row(verticalAlignment = Alignment.Bottom) {
                Text(
                    value?.let { "%.2f".format(it) } ?: "—",
                    style = MaterialTheme.typography.titleLarge,
                    color = if (value == null) MaterialTheme.colorScheme.error
                    else if (selected) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.onSurface,
                )
                val unit = unitFor(key)
                if (unit.isNotEmpty()) {
                    Text(
                        " $unit",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                    )
                }
            }
        }
    }
}

@Composable
private fun SparklineCard(
    who: AnalyzerKey,
    key: String,
    history: TelemetryHistory,
    version: Int,
) {
    val series = remember(who, key, version) { history.series(who, key) }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(10.dp)) {
            val mn = series.minOfOrNull { it.second }
            val mx = series.maxOfOrNull { it.second }
            Text(
                "${shortName(key)} — ${series.size} pts" +
                    (if (mn != null && mx != null) " · min %.2f · max %.2f".format(mn, mx) else ""),
                style = MaterialTheme.typography.labelSmall,
            )
            val lineColor = MaterialTheme.colorScheme.primary
            Canvas(
                Modifier
                    .fillMaxWidth()
                    .height(110.dp)
                    .padding(top = 6.dp),
            ) {
                if (series.size < 2 || mn == null || mx == null) return@Canvas
                val span = (mx - mn).takeIf { it > 1e-9 } ?: 1.0
                val t0 = series.first().first
                val t1 = series.last().first
                val tSpan = (t1 - t0).takeIf { it > 0 } ?: 1L
                val path = Path()
                series.forEachIndexed { i, (ts, v) ->
                    val x = ((ts - t0).toDouble() / tSpan).toFloat() * size.width
                    val y = size.height - ((v - mn) / span).toFloat() * size.height
                    if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
                }
                drawPath(path, lineColor, style = Stroke(width = 3f))
            }
        }
    }
}
