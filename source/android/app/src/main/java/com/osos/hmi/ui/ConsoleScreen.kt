package com.osos.hmi.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import com.osos.hmi.AppContainer
import com.osos.hmi.console.ConsoleInterpreter

// Authoring alarm bands and digit binds as text. The Alarms/Commands dialogs
// remain the guided path; this is the one that scales to a meter matrix.
@Composable
fun ConsoleScreen(c: AppContainer) {
    val lines by c.consoleLines.collectAsState()
    val interp = remember(c) { ConsoleInterpreter(c) }
    val listState = rememberLazyListState()
    var input by remember { mutableStateOf("") }

    val send = {
        if (input.isNotBlank()) {
            interp.submit(input)
            input = ""
        }
    }

    LaunchedEffect(lines.size) {
        if (lines.isNotEmpty()) listState.scrollToItem(lines.lastIndex)
    }

    Column(
        Modifier
            .fillMaxSize()
            .imePadding(),
    ) {
        LazyColumn(
            state = listState,
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
                .padding(horizontal = 12.dp),
            verticalArrangement = Arrangement.spacedBy(1.dp),
        ) {
            items(lines) { line ->
                Text(
                    line,
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                    color = lineColor(line),
                )
            }
        }

        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedTextField(
                value = input,
                onValueChange = { input = it },
                modifier = Modifier.weight(1f),
                singleLine = true,
                textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                placeholder = {
                    Text(
                        "rule V_* 207 253",
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = FontFamily.Monospace,
                    )
                },
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { send() }),
            )
            Button(onClick = send, enabled = input.isNotBlank()) { Text("Run") }
        }
    }
}

@Composable
private fun lineColor(line: String): Color = when {
    line.startsWith("✗") -> MaterialTheme.colorScheme.error
    line.startsWith("✓") -> MaterialTheme.colorScheme.primary
    line.startsWith("> ") -> MaterialTheme.colorScheme.onSurface.copy(alpha = 0.55f)
    else -> MaterialTheme.colorScheme.onSurface.copy(alpha = 0.85f)
}
