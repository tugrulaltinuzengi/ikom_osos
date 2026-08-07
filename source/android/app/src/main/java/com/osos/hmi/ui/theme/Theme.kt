package com.osos.hmi.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Dark scheme matching the browser HMI's look.
private val Scheme = darkColorScheme(
    primary = Color(0xFF4FC3F7),
    onPrimary = Color(0xFF00303F),
    secondary = Color(0xFF80CBC4),
    background = Color(0xFF101418),
    surface = Color(0xFF181D23),
    surfaceVariant = Color(0xFF232A32),
    error = Color(0xFFFF6E6E),
)

@Composable
fun OsosTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = Scheme, content = content)
}
