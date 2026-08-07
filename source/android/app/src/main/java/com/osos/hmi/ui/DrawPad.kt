package com.osos.hmi.ui

import android.graphics.Bitmap
import android.graphics.Paint
import androidx.compose.foundation.Image
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.drag
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.dp
import com.osos.hmi.nn.Preprocess
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

// The 280x280 drawing surface, matching www/draw.js exactly: black canvas,
// white stroke 20 with round cap/join (in 280-space), 650 ms pen-up idle
// before the grid is produced (multi-stroke digits like 4/5/7).
@Composable
fun DrawPad(
    modifier: Modifier = Modifier,
    clearSignal: Int,
    onPenDown: () -> Unit = {},
    onGrid: (IntArray) -> Unit,
) {
    val bitmap = remember { Bitmap.createBitmap(Preprocess.SIZE, Preprocess.SIZE, Bitmap.Config.ARGB_8888) }
    val canvas = remember { android.graphics.Canvas(bitmap).apply { drawColor(android.graphics.Color.BLACK) } }
    val paint = remember {
        Paint().apply {
            color = android.graphics.Color.WHITE
            style = Paint.Style.STROKE
            strokeWidth = Preprocess.STROKE
            strokeCap = Paint.Cap.ROUND
            strokeJoin = Paint.Join.ROUND
            isAntiAlias = true
        }
    }
    var frame by remember { mutableIntStateOf(0) }
    var penSeq by remember { mutableIntStateOf(0) }
    val penDown = remember { booleanArrayOf(false) }
    val hasInk = remember { booleanArrayOf(false) }

    LaunchedEffect(clearSignal) {
        canvas.drawColor(android.graphics.Color.BLACK)
        hasInk[0] = false
        frame++
    }

    // pen-up idle timer: restarts on every pen event; only fires when up
    LaunchedEffect(penSeq) {
        if (penSeq > 0 && !penDown[0] && hasInk[0]) {
            delay(650)
            val px = IntArray(Preprocess.SIZE * Preprocess.SIZE)
            bitmap.getPixels(px, 0, Preprocess.SIZE, 0, 0, Preprocess.SIZE, Preprocess.SIZE)
            val grid = withContext(Dispatchers.Default) { Preprocess.toMnist(px) }
            if (grid != null) onGrid(grid)
        }
    }

    Box(
        modifier = modifier
            .aspectRatio(1f)
            .border(1.dp, MaterialTheme.colorScheme.surfaceVariant)
            .pointerInput(Unit) {
                awaitEachGesture {
                    val down = awaitFirstDown()
                    penDown[0] = true
                    hasInk[0] = true
                    penSeq++
                    onPenDown()
                    val scale = Preprocess.SIZE.toFloat() / size.width
                    var lastX = down.position.x * scale
                    var lastY = down.position.y * scale
                    canvas.drawPoint(lastX, lastY, paint) // dot for a tap
                    frame++
                    down.consume()
                    drag(down.id) { change ->
                        val x = change.position.x * scale
                        val y = change.position.y * scale
                        canvas.drawLine(lastX, lastY, x, y, paint)
                        lastX = x
                        lastY = y
                        frame++
                        change.consume()
                    }
                    penDown[0] = false
                    penSeq++
                }
            }
    ) {
        val img = remember(frame) { bitmap.asImageBitmap() }
        Image(bitmap = img, contentDescription = "drawing pad", modifier = Modifier.fillMaxSize())
    }
}
