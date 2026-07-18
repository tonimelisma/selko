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
    val successText: Color,
    val onSuccess: Color,
    val successContainer: Color,
    val onSuccessContainer: Color,
    val warning: Color,
    val onWarning: Color,
    val rust: Color,
    val link: Color,
    val changed: Color,
    val faint: Color,
    val divider: Color,
    val badgeNewBackground: Color,
    val badgeNewForeground: Color,
    val badgeChangedBackground: Color,
    val badgeChangedForeground: Color
)

private val LightSelkoColors = SelkoColors(
    success = SelkoSuccess,
    successText = SelkoSuccessText,
    onSuccess = SelkoOnSuccess,
    successContainer = SelkoSuccessContainer,
    onSuccessContainer = SelkoOnSuccessContainer,
    warning = SelkoWarning,
    onWarning = SelkoOnWarning,
    rust = SelkoRust,
    link = SelkoLink,
    changed = SelkoChanged,
    faint = SelkoFaint,
    divider = SelkoDivider,
    badgeNewBackground = SelkoBadgeNewBackground,
    badgeNewForeground = SelkoBadgeNewForeground,
    badgeChangedBackground = SelkoBadgeChangedBackground,
    badgeChangedForeground = SelkoBadgeChangedForeground
)

private val DarkSelkoColors = SelkoColors(
    success = SelkoSuccessDark,
    successText = SelkoSuccessDark,
    onSuccess = SelkoOnSuccess,
    successContainer = SelkoSuccessContainerDark,
    onSuccessContainer = SelkoOnSuccessContainerDark,
    warning = SelkoWarningDark,
    onWarning = SelkoOnWarning,
    rust = SelkoRustDark,
    link = SelkoLinkDark,
    changed = SelkoChangedDark,
    faint = SelkoFaintDark,
    divider = SelkoDividerDark,
    badgeNewBackground = SelkoBadgeNewBackgroundDark,
    badgeNewForeground = SelkoBadgeNewForegroundDark,
    badgeChangedBackground = SelkoBadgeChangedBackgroundDark,
    badgeChangedForeground = SelkoBadgeChangedForegroundDark
)

val LocalSelkoColors = staticCompositionLocalOf { LightSelkoColors }

private val LightColorScheme = lightColorScheme(
    primary = SelkoPrimary,
    onPrimary = SelkoOnPrimary,
    primaryContainer = SelkoPrimaryContainer,
    onPrimaryContainer = SelkoOnPrimaryContainer,
    secondary = SelkoRust,
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
    onPrimary = SelkoOnPrimaryDark,
    primaryContainer = SelkoPrimaryContainerDark,
    onPrimaryContainer = SelkoOnPrimaryContainerDark,
    secondary = SelkoRustDark,
    onSecondary = SelkoOnPrimaryDark,
    background = SelkoBackgroundDark,
    onBackground = SelkoOnBackgroundDark,
    surface = SelkoSurfaceDark,
    onSurface = SelkoOnSurfaceDark,
    surfaceVariant = SelkoSurfaceVariantDark,
    onSurfaceVariant = SelkoOnSurfaceVariantDark,
    outline = SelkoOutlineDark,
    outlineVariant = SelkoOutlineVariantDark,
    error = SelkoErrorDark,
    onError = SelkoOnPrimaryDark
)

private val SelkoShapes = Shapes(
    extraSmall = RoundedCornerShape(12.dp),
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(14.dp),
    large = RoundedCornerShape(20.dp),
    extraLarge = RoundedCornerShape(20.dp)
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
