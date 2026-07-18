package net.melisma.selko.ui.theme

import androidx.compose.ui.graphics.Color
import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import net.melisma.selko.ui.components.SelkoControlMetrics
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class DesignTokenContractTest {
    private val manifest = Json.parseToJsonElement(File("../../design/tokens.json").readText()).jsonObject

    @Test
    fun `android colors and geometry match canonical manifest`() {
        val light = manifest.getValue("color").jsonObject.getValue("light").jsonObject
        assertEquals(color(light, "primary"), SelkoPrimary)
        assertEquals(color(light, "onPrimary"), SelkoOnPrimary)
        assertEquals(color(light, "success"), SelkoSuccess)
        assertEquals(color(light, "onSuccess"), SelkoOnSuccess)
        assertEquals(color(light, "muted"), SelkoOnSurfaceVariant)
        assertEquals(color(light, "faint"), SelkoFaint)
        assertEquals(44f, SelkoControlMetrics.minimumTarget.value)
        assertEquals(46f, SelkoControlMetrics.inputHeight.value)
        assertEquals(14f, SelkoControlMetrics.controlRadius.value)
        assertEquals(20f, SelkoControlMetrics.cardRadius.value)
    }

    @Test
    fun `canonical text pairings meet AA contrast`() {
        for (mode in listOf("light", "dark")) {
            val colors = manifest.getValue("color").jsonObject.getValue(mode).jsonObject
            listOf(
                "ink" to "paper", "ink" to "surface", "muted" to "paper",
                "faint" to "paper", "onPrimary" to "primary", "onSuccess" to "success",
                "onError" to "error", "newForeground" to "newBackground",
                "changedForeground" to "changedBackground"
            ).forEach { (foreground, background) ->
                assertTrue("$mode $foreground/$background", contrast(hex(colors, foreground), hex(colors, background)) >= 4.5)
            }
        }
    }

    private fun hex(colors: kotlinx.serialization.json.JsonObject, key: String) = colors.getValue(key).jsonPrimitive.content
    private fun color(colors: kotlinx.serialization.json.JsonObject, key: String): Color {
        val rgb = hex(colors, key).removePrefix("#").chunked(2).map { it.toInt(16) / 255f }
        return Color(red = rgb[0], green = rgb[1], blue = rgb[2], alpha = 1f)
    }
    private fun contrast(a: String, b: String): Double {
        fun luminance(hex: String): Double {
            val rgb = hex.removePrefix("#").chunked(2).map { it.toInt(16) / 255.0 }
            val linear = rgb.map { if (it <= 0.04045) it / 12.92 else Math.pow((it + 0.055) / 1.055, 2.4) }
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
        }
        val values = listOf(luminance(a), luminance(b)).sortedDescending()
        return (values[0] + 0.05) / (values[1] + 0.05)
    }
}
