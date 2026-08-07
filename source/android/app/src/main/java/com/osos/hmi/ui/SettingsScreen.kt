package com.osos.hmi.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.osos.hmi.AppContainer

@Composable
fun SettingsScreen(c: AppContainer) {
    val p = c.prefs
    var host by remember { mutableStateOf(p.host) }
    var port by remember { mutableStateOf(p.port.toString()) }
    var tls by remember { mutableStateOf(p.tls) }
    var user by remember { mutableStateOf(p.user) }
    var pass by remember { mutableStateOf(p.pass) }
    var offlineAfter by remember { mutableStateOf(p.offlineAfterSec.toString()) }
    var confMin by remember { mutableFloatStateOf(p.confMin) }
    var simMin by remember { mutableFloatStateOf(p.simMin) }
    var headMin by remember { mutableFloatStateOf(p.headMin) }
    var saved by remember { mutableStateOf<String?>(null) }

    val fleetNow by c.fleet.collectAsState()
    val filters by c.client.activeFilters.collectAsState()
    val connected by c.client.connected.collectAsState()

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("Broker", style = MaterialTheme.typography.titleSmall)
        
        OutlinedTextField(
            value = host, 
            onValueChange = { host = it }, 
            label = { Text("host") }, 
            singleLine = true, 
            modifier = Modifier.fillMaxWidth()
        )
        
        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp), 
            verticalAlignment = Alignment.CenterVertically
        ) {
            OutlinedTextField(
                value = port, 
                onValueChange = { port = it }, 
                label = { Text("port") }, 
                singleLine = true, 
                modifier = Modifier.weight(1f)
            )
            Text("TLS")
            Switch(checked = tls, onCheckedChange = { tls = it })
        }
        
        OutlinedTextField(
            value = user, 
            onValueChange = { user = it }, 
            label = { Text("username (empty = anonymous)") }, 
            singleLine = true, 
            modifier = Modifier.fillMaxWidth()
        )
        
        OutlinedTextField(
            value = pass, 
            onValueChange = { pass = it }, 
            label = { Text("password") }, 
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(), 
            modifier = Modifier.fillMaxWidth()
        )
        
        Text("Recognition thresholds", style = MaterialTheme.typography.titleSmall)
        ThresholdSlider("digit confidence ≥ %.2f".format(confMin), confMin) { confMin = it }
        ThresholdSlider("cosine similarity ≥ %.2f".format(simMin), simMin) { simMin = it }
        ThresholdSlider("trained-head prob ≥ %.2f".format(headMin), headMin) { headMin = it }

        OutlinedTextField(
            value = offlineAfter, 
            onValueChange = { offlineAfter = it },
            label = { Text("offline alarm after (seconds without telemetry)") },
            singleLine = true, 
            modifier = Modifier.fillMaxWidth()
        )

        // Bad input is refused, never silently replaced: substituting 1883 for
        // a typo while the field still shows the typo is how you end up
        // debugging a broker you are not actually connected to.
        Button(onClick = {
            val portNum = port.trim().toIntOrNull()
            val offlineNum = offlineAfter.trim().toIntOrNull()
            when {
                host.isBlank() -> saved = "✗ host is empty"
                portNum == null || portNum !in 1..65535 -> saved = "✗ port must be 1–65535"
                offlineNum == null || offlineNum < 1 ->
                    saved = "✗ offline alarm needs a positive number of seconds"
                else -> {
                    p.host = host.trim()
                    p.port = portNum
                    p.tls = tls
                    p.user = user.trim()
                    p.pass = pass
                    p.confMin = confMin
                    p.simMin = simMin
                    p.headMin = headMin
                    p.offlineAfterSec = offlineNum

                    c.client.connect(p.brokerConfig())
                    saved = "saved — reconnecting to ${p.host}:${p.port}"
                }
            }
        }) {
            Text("Save & reconnect")
        }

        saved?.let {
            Text(
                it,
                style = MaterialTheme.typography.bodySmall,
                color = if (it.startsWith("✗")) MaterialTheme.colorScheme.error
                else MaterialTheme.colorScheme.primary,
            )
        }

        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("Fleet Status", style = MaterialTheme.typography.titleSmall)
                Text(
                    "Discovered modems: ${fleetNow.modems.size} · " +
                        "analyzers: ${fleetNow.allAnalyzers.size}",
                    style = MaterialTheme.typography.bodySmall,
                )
                // The filters actually held, not a guess. Analyzer telemetry
                // follows the selected / open modem, so this set changes as you
                // navigate — which is exactly what you want to see when a tile
                // stays empty.
                Text(
                    if (connected) "Active subscriptions (${filters.size})"
                    else "Active subscriptions — not connected",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                )
                filters.sorted().forEach { f ->
                    Text(
                        "  $f",
                        style = MaterialTheme.typography.labelSmall,
                        fontFamily = FontFamily.Monospace,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f),
                    )
                }
            }
        }

        Spacer(Modifier.padding(4.dp))
    }
}

@Composable
private fun ThresholdSlider(label: String, value: Float, onChange: (Float) -> Unit) {
    Column {
        Text(label, style = MaterialTheme.typography.labelMedium)
        Slider(value = value, onValueChange = onChange, valueRange = 0.5f..1f)
    }
}