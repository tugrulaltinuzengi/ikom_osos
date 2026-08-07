package com.osos.hmi.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Create
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.osos.hmi.AppContainer

@Composable
fun AppRoot(c: AppContainer) {
    val tab by c.uiTab.collectAsState()
    val connected by c.client.connected.collectAsState()
    val fleetNow by c.fleet.collectAsState()
    val selNow by c.selected.collectAsState()
    val status = selNow?.let { fleetNow.modems[it.mid]?.status }
    val alarms by c.alarms.active.collectAsState()

    // six destinations on a ~344 dp screen ⇒ ~57 dp each: labels are kept
    // short so none of them wraps ("Commands" used to break as "Command/s")
    val tabs = listOf(
        "Monitor" to Icons.Filled.Home,
        "Draw" to Icons.Filled.Create,
        "Cmds" to Icons.AutoMirrored.Filled.List,
        "Alarms" to Icons.Filled.Notifications,
        "Console" to Icons.AutoMirrored.Filled.KeyboardArrowRight,
        "Settings" to Icons.Filled.Settings,
    )

    Scaffold(
        topBar = {
            // targetSdk 35 ⇒ Android 15 draws edge-to-edge: without the
            // status-bar inset the title sits under the system clock
            Surface(color = MaterialTheme.colorScheme.surface) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .windowInsetsPadding(WindowInsets.statusBars)
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("OSOS HMI", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.width(8.dp))
                    Text(
                        selNow?.let { fleetNow.analyzer(it.mid, it.aid)?.name ?: it.aid }
                            ?: "no analyzer",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                    )
                    Spacer(Modifier.weight(1f))
                    val (pillText, pillColor) = when {
                        !connected -> "no broker" to Color(0xFF9E9E9E)
                        status?.state == "online" -> "gateway online" to Color(0xFF66BB6A)
                        else -> "gateway offline" to Color(0xFFFFA726)
                    }
                    Box(
                        Modifier
                            .size(10.dp)
                            .background(pillColor, CircleShape)
                    )
                    Spacer(Modifier.width(6.dp))
                    Text(pillText, style = MaterialTheme.typography.labelMedium)
                }
            }
        },
        bottomBar = {
            // NavigationBar applies the navigation-bar inset itself — nothing
            // to add here, and adding it would pad twice
            NavigationBar {
                tabs.forEachIndexed { i, (label, icon) ->
                    NavigationBarItem(
                        selected = tab == i,
                        onClick = { c.uiTab.value = i },
                        icon = {
                            // the alarm count rides the icon as a badge; as a
                            // label suffix it pushed "Alarms (3)" onto two lines
                            if (i == 3 && alarms.isNotEmpty()) {
                                BadgedBox(badge = { Badge { Text("${alarms.size}") } }) {
                                    Icon(icon, contentDescription = label)
                                }
                            } else {
                                Icon(icon, contentDescription = label)
                            }
                        },
                        label = {
                            Text(
                                label,
                                style = MaterialTheme.typography.labelSmall,
                                maxLines = 1,
                                softWrap = false,
                            )
                        },
                    )
                }
            }
        },
    ) { pad ->
        Box(Modifier.padding(pad).fillMaxSize()) {
            when (tab) {
                0 -> MonitorScreen(c)
                1 -> DrawScreen(c)
                2 -> CommandsScreen(c)
                3 -> AlarmsScreen(c)
                4 -> ConsoleScreen(c)
                else -> SettingsScreen(c)
            }
        }
    }
}
