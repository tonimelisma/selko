package net.melisma.selko.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp

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
    small = RoundedCornerShape(2.dp),
    medium = RoundedCornerShape(2.dp),
    large = RoundedCornerShape(2.dp),
    extraLarge = RoundedCornerShape(2.dp)
)

@Composable
fun SelkoTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography,
        shapes = SelkoShapes,
        content = content
    )
}
