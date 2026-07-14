package net.melisma.selko.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/**
 * The Selko mark: a coral calendar tile with three event blocks settling into
 * place — two small squares on top (right one faded) and a wide bar below.
 * Geometry mirrors the web LogoMark's 40x40 viewBox.
 */
@Composable
fun SelkoLogoMark(
    modifier: Modifier = Modifier.size(44.dp),
    color: Color = MaterialTheme.colorScheme.primary
) {
    val blockColor = MaterialTheme.colorScheme.onPrimary

    Canvas(modifier = modifier) {
        val u = size.minDimension / 40f
        drawRoundRect(
            color = color,
            topLeft = Offset(0f, 0f),
            size = Size(40f * u, 40f * u),
            cornerRadius = CornerRadius(12f * u, 12f * u)
        )
        val blockRadius = CornerRadius(2.5f * u, 2.5f * u)
        drawRoundRect(
            color = blockColor,
            topLeft = Offset(9f * u, 10f * u),
            size = Size(9f * u, 9f * u),
            cornerRadius = blockRadius
        )
        drawRoundRect(
            color = blockColor.copy(alpha = 0.55f),
            topLeft = Offset(22f * u, 10f * u),
            size = Size(9f * u, 9f * u),
            cornerRadius = blockRadius
        )
        drawRoundRect(
            color = blockColor.copy(alpha = 0.85f),
            topLeft = Offset(9f * u, 23f * u),
            size = Size(22f * u, 8f * u),
            cornerRadius = blockRadius
        )
    }
}
