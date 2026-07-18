package net.melisma.selko.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import net.melisma.selko.ui.theme.SelkoTheme

object SelkoControlMetrics {
    val minimumTarget = 44.dp
    val inputHeight = 46.dp
    val horizontalPadding = 16.dp
    val contentGap = 8.dp
    val icon = 20.dp
    val navigationRadius = 12.dp
    val controlRadius = 14.dp
    val cardRadius = 20.dp
    val pillRadius = 999.dp
}

enum class SelkoActionRole { Primary, Secondary, Success, DestructiveOutline, Tertiary }

@Composable
fun SelkoButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    role: SelkoActionRole = SelkoActionRole.Primary,
    enabled: Boolean = true,
    loading: Boolean = false,
    icon: ImageVector? = null
) {
    val shape = RoundedCornerShape(SelkoControlMetrics.controlRadius)
    val content: @Composable () -> Unit = {
        if (loading) {
            CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
        } else {
            icon?.let {
                Icon(it, contentDescription = null, modifier = Modifier.size(SelkoControlMetrics.icon))
                Spacer(Modifier.width(SelkoControlMetrics.contentGap))
            }
            Text(text, style = MaterialTheme.typography.labelLarge)
        }
    }
    val sized = modifier.defaultMinSize(minHeight = SelkoControlMetrics.minimumTarget)
    val active = enabled && !loading
    when (role) {
        SelkoActionRole.Primary -> Button(
            onClick = onClick, modifier = sized, enabled = active, shape = shape,
            colors = ButtonDefaults.buttonColors(
                containerColor = MaterialTheme.colorScheme.primary,
                contentColor = MaterialTheme.colorScheme.onPrimary
            ),
            contentPadding = PaddingValues(horizontal = SelkoControlMetrics.horizontalPadding),
            content = { content() }
        )
        SelkoActionRole.Secondary -> Button(
            onClick = onClick, modifier = sized, enabled = active, shape = shape,
            colors = ButtonDefaults.buttonColors(
                containerColor = MaterialTheme.colorScheme.surfaceVariant,
                contentColor = MaterialTheme.colorScheme.onSurface
            ),
            contentPadding = PaddingValues(horizontal = SelkoControlMetrics.horizontalPadding),
            content = { content() }
        )
        SelkoActionRole.Success -> Button(
            onClick = onClick, modifier = sized, enabled = active, shape = shape,
            colors = ButtonDefaults.buttonColors(
                containerColor = SelkoTheme.colors.success,
                contentColor = SelkoTheme.colors.onSuccess
            ),
            contentPadding = PaddingValues(horizontal = SelkoControlMetrics.horizontalPadding),
            content = { content() }
        )
        SelkoActionRole.DestructiveOutline -> OutlinedButton(
            onClick = onClick, modifier = sized, enabled = active, shape = shape,
            colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
            border = BorderStroke(1.5.dp, if (active) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.outline),
            contentPadding = PaddingValues(horizontal = SelkoControlMetrics.horizontalPadding),
            content = { content() }
        )
        SelkoActionRole.Tertiary -> TextButton(
            onClick = onClick, modifier = sized, enabled = active, shape = shape,
            colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.onSurface),
            contentPadding = PaddingValues(horizontal = SelkoControlMetrics.horizontalPadding),
            content = { content() }
        )
    }
}

@Composable
fun SelkoIconButton(
    icon: ImageVector,
    contentDescription: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    destructive: Boolean = false,
    enabled: Boolean = true
) {
    IconButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.size(SelkoControlMetrics.minimumTarget),
        colors = IconButtonDefaults.iconButtonColors(
            contentColor = if (destructive) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface
        )
    ) {
        Icon(icon, contentDescription, modifier = Modifier.size(SelkoControlMetrics.icon))
    }
}

@Composable
fun SelkoStatusIndicator(
    text: String,
    icon: ImageVector,
    modifier: Modifier = Modifier,
    color: Color = MaterialTheme.colorScheme.onSurfaceVariant
) {
    Row(
        modifier = modifier.semantics { liveRegion = LiveRegionMode.Polite },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Icon(icon, contentDescription = null, modifier = Modifier.size(20.dp), tint = color)
        Text(text, style = MaterialTheme.typography.bodySmall, color = color)
    }
}

enum class SelkoTagRole { New, Changed, Neutral }

@Composable
fun SelkoStateTag(text: String, role: SelkoTagRole, modifier: Modifier = Modifier) {
    val background = when (role) {
        SelkoTagRole.New -> SelkoTheme.colors.badgeNewBackground
        SelkoTagRole.Changed -> SelkoTheme.colors.badgeChangedBackground
        SelkoTagRole.Neutral -> MaterialTheme.colorScheme.surfaceVariant
    }
    val foreground = when (role) {
        SelkoTagRole.New -> SelkoTheme.colors.badgeNewForeground
        SelkoTagRole.Changed -> SelkoTheme.colors.badgeChangedForeground
        SelkoTagRole.Neutral -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    Text(
        text = text.uppercase(),
        style = MaterialTheme.typography.labelSmall,
        color = foreground,
        modifier = modifier.clip(RoundedCornerShape(SelkoControlMetrics.pillRadius))
            .background(background).padding(horizontal = 8.dp, vertical = 4.dp)
    )
}

@Composable
fun SelkoLabeledSwitch(
    title: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
    supportingText: String? = null,
    enabled: Boolean = true,
    checkedLabel: String = "Included",
    uncheckedLabel: String = "Excluded"
) {
    Row(
        modifier = modifier.defaultMinSize(minHeight = SelkoControlMetrics.minimumTarget)
            .semantics { role = Role.Switch },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(if (checked) checkedLabel else uncheckedLabel, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            supportingText?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = SelkoTheme.colors.faint) }
        }
        Switch(
            checked = checked, onCheckedChange = onCheckedChange, enabled = enabled,
            colors = SwitchDefaults.colors(
                checkedTrackColor = MaterialTheme.colorScheme.primary,
                checkedThumbColor = MaterialTheme.colorScheme.onPrimary,
                checkedIconColor = MaterialTheme.colorScheme.primary
            ),
            thumbContent = if (checked) {{ Text("✓", style = MaterialTheme.typography.labelSmall) }} else null
        )
    }
}

@Composable
fun SelkoRemovableChip(
    text: String,
    onRemove: () -> Unit,
    removeIcon: ImageVector,
    removeDescription: String,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier.clip(RoundedCornerShape(SelkoControlMetrics.pillRadius))
            .background(MaterialTheme.colorScheme.surfaceVariant).padding(start = 16.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(text, modifier = Modifier.weight(1f, fill = false), maxLines = 1, overflow = TextOverflow.Ellipsis)
        SelkoIconButton(removeIcon, removeDescription, onRemove, destructive = true)
    }
}
