package net.melisma.selko.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

@Immutable
data class SelkoColors(
    val success: Color,
    val onSuccess: Color,
    val successContainer: Color,
    val onSuccessContainer: Color,
    val warning: Color,
    val onWarning: Color
)

private val LightSelkoColors = SelkoColors(
    success = SelkoSuccess,
    onSuccess = SelkoOnSuccess,
    successContainer = SelkoSuccessContainer,
    onSuccessContainer = SelkoOnSuccessContainer,
    warning = SelkoWarning,
    onWarning = SelkoOnWarning
)

private val DarkSelkoColors = SelkoColors(
    success = SelkoSuccessDark,
    onSuccess = SelkoOnSuccess,
    successContainer = SelkoSuccessContainerDark,
    onSuccessContainer = SelkoOnSuccessContainerDark,
    warning = SelkoWarningDark,
    onWarning = SelkoOnWarning
)

val LocalSelkoColors = staticCompositionLocalOf { LightSelkoColors }

private val LightColorScheme = lightColorScheme(
    primary = SelkoPrimary,
    onPrimary = SelkoOnPrimary,
    primaryContainer = SelkoPrimaryContainer,
    onPrimaryContainer = SelkoOnPrimaryContainer,
    secondary = SelkoPrimary,
    onSecondary = SelkoOnPrimary,
    background = SelkoBackground,
    onBackground = SelkoOnBackground,
    surface = SelkoSurface,
    onSurface = SelkoOnSurface,
    surfaceVariant = SelkoSurfaceVariant,
    onSurfaceVariant = SelkoOnSurfaceVariant,
    outline = SelkoOutline,
    outlineVariant = SelkoOutlineVariant,
    error = SelkoError,
    onError = SelkoOnError
)

private val DarkColorScheme = darkColorScheme(
    primary = SelkoPrimaryDark,
    onPrimary = SelkoOnPrimary,
    primaryContainer = SelkoPrimary,
    onPrimaryContainer = SelkoOnPrimary,
    secondary = SelkoPrimaryDark,
    onSecondary = SelkoOnPrimary,
    background = SelkoBackgroundDark,
    onBackground = SelkoOnBackgroundDark,
    surface = SelkoSurfaceDark,
    onSurface = SelkoOnSurfaceDark,
    surfaceVariant = SelkoSurfaceVariantDark,
    onSurfaceVariant = SelkoOnSurfaceVariantDark,
    outline = SelkoOutlineDark,
    outlineVariant = SelkoOutlineVariantDark,
    error = SelkoErrorDark,
    onError = SelkoOnError
)

private val SelkoShapes = Shapes(
    extraSmall = RoundedCornerShape(2.dp),
    small = RoundedCornerShape(4.dp),
    medium = RoundedCornerShape(8.dp),
    large = RoundedCornerShape(12.dp),
    extraLarge = RoundedCornerShape(16.dp)
)

@Composable
fun SelkoTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme
    val selkoColors = if (darkTheme) DarkSelkoColors else LightSelkoColors

    CompositionLocalProvider(LocalSelkoColors provides selkoColors) {
        MaterialTheme(
            colorScheme = colorScheme,
            typography = Typography,
            shapes = SelkoShapes,
            content = content
        )
    }
}

object SelkoTheme {
    val colors: SelkoColors
        @Composable
        get() = LocalSelkoColors.current
}
