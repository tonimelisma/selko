package net.melisma.selko.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

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

@Composable
fun SelkoTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography,
        content = content
    )
}
