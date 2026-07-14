package net.melisma.selko.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp

@Composable
fun SelkoLogoMark(
    modifier: Modifier = Modifier.size(44.dp),
    color: Color = MaterialTheme.colorScheme.primary
) {
    val onPrimary = MaterialTheme.colorScheme.onPrimary

    Canvas(modifier = modifier) {
        val radius = size.minDimension * 0.22f
        drawRoundRect(
            color = color,
            topLeft = Offset(size.width * 0.1f, size.height * 0.1f),
            size = androidx.compose.ui.geometry.Size(size.width * 0.8f, size.height * 0.8f),
            cornerRadius = CornerRadius(radius, radius)
        )
        drawLine(
            color = onPrimary,
            start = Offset(size.width * 0.28f, size.height * 0.36f),
            end = Offset(size.width * 0.72f, size.height * 0.36f),
            strokeWidth = size.minDimension * 0.07f,
            cap = StrokeCap.Round
        )
        drawLine(
            color = onPrimary,
            start = Offset(size.width * 0.28f, size.height * 0.36f),
            end = Offset(size.width * 0.28f, size.height * 0.72f),
            strokeWidth = size.minDimension * 0.07f,
            cap = StrokeCap.Round
        )
        drawLine(
            color = onPrimary,
            start = Offset(size.width * 0.28f, size.height * 0.72f),
            end = Offset(size.width * 0.72f, size.height * 0.72f),
            strokeWidth = size.minDimension * 0.07f,
            cap = StrokeCap.Round
        )
        drawLine(
            color = onPrimary,
            start = Offset(size.width * 0.72f, size.height * 0.72f),
            end = Offset(size.width * 0.72f, size.height * 0.36f),
            strokeWidth = size.minDimension * 0.07f,
            cap = StrokeCap.Round
        )
        drawCircle(
            color = onPrimary,
            radius = size.minDimension * 0.055f,
            center = Offset(size.width * 0.42f, size.height * 0.54f)
        )
        drawCircle(
            color = onPrimary,
            radius = size.minDimension * 0.055f,
            center = Offset(size.width * 0.58f, size.height * 0.54f)
        )
    }
}
