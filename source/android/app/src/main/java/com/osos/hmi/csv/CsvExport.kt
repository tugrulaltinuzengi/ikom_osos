package com.osos.hmi.csv

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import com.osos.hmi.data.CustomCommandStore
import java.io.File

// Same format hmi.js exports and neural_net_c/src/data_mnist.cpp loads:
// one line per sample, "label,p0..p783", custom labels start at 10.
// Feeds the phase-2 PC retraining of the full net with a wider output layer.
object CsvExport {

    fun buildCsv(cmds: List<CustomCommandStore.Cmd>): String {
        val sb = StringBuilder()
        cmds.forEachIndexed { ci, cmd ->
            cmd.samples.forEach { s ->
                sb.append(10 + ci)
                s.forEach { v -> sb.append(',').append(v) }
                sb.append('\n')
            }
        }
        return sb.toString()
    }

    fun exportAndShare(ctx: Context, cmds: List<CustomCommandStore.Cmd>) {
        val dir = File(ctx.filesDir, "export").apply { mkdirs() }
        val f = File(dir, "custom_symbols.csv")
        f.writeText(buildCsv(cmds))
        val uri = FileProvider.getUriForFile(ctx, "com.osos.hmi.fileprovider", f)
        val send = Intent(Intent.ACTION_SEND)
            .setType("text/csv")
            .putExtra(Intent.EXTRA_STREAM, uri)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        ctx.startActivity(
            Intent.createChooser(send, "Export samples CSV")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
    }
}
