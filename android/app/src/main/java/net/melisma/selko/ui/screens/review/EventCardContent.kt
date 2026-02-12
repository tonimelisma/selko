package net.melisma.selko.ui.screens.review

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.datetime.Instant
import kotlinx.datetime.TimeZone
import kotlinx.datetime.toLocalDateTime
import net.melisma.selko.data.model.CalendarEvent

@Composable
fun EventCardContent(
    event: CalendarEvent,
    isProcessing: Boolean,
    onApprove: () -> Unit,
    onReject: () -> Unit,
    onEdit: () -> Unit
) {
    var isExpanded by remember { mutableStateOf(false) }

    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp)
        ) {
            // Title
            Text(
                text = event.title,
                style = MaterialTheme.typography.titleMedium,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )

            Spacer(modifier = Modifier.height(8.dp))

            // Date/Time
            event.startDatetime?.let { start ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = Icons.Filled.Schedule,
                        contentDescription = "Event time",
                        modifier = Modifier.size(16.dp),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Spacer(modifier = Modifier.width(4.dp))
                    Text(
                        text = formatDateTimeRange(start, event.endDatetime, event.allDay),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }

            // Location
            event.location?.let { location ->
                Spacer(modifier = Modifier.height(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = Icons.Filled.LocationOn,
                        contentDescription = "Event location",
                        modifier = Modifier.size(16.dp),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Spacer(modifier = Modifier.width(4.dp))
                    Text(
                        text = location,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
            }

            // Expandable description
            event.description?.let { description ->
                if (description.isNotBlank()) {
                    Spacer(modifier = Modifier.height(8.dp))
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { isExpanded = !isExpanded },
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = "Description",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.primary
                        )
                        Icon(
                            imageVector = if (isExpanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                            contentDescription = if (isExpanded) "Collapse description" else "Expand description",
                            modifier = Modifier.size(20.dp),
                            tint = MaterialTheme.colorScheme.primary
                        )
                    }
                    AnimatedVisibility(visible = isExpanded) {
                        Text(
                            text = description,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = 4.dp)
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            // Action buttons
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End)
            ) {
                if (isProcessing) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(24.dp),
                        strokeWidth = 2.dp
                    )
                } else {
                    FilledTonalIconButton(
                        onClick = onApprove
                    ) {
                        Icon(
                            imageVector = Icons.Filled.Check,
                            contentDescription = "Approve",
                            modifier = Modifier.size(20.dp)
                        )
                    }
                    IconButton(
                        onClick = onEdit
                    ) {
                        Icon(
                            imageVector = Icons.Filled.Edit,
                            contentDescription = "Edit",
                            modifier = Modifier.size(20.dp)
                        )
                    }
                    IconButton(
                        onClick = onReject
                    ) {
                        Icon(
                            imageVector = Icons.Filled.Close,
                            contentDescription = "Reject",
                            modifier = Modifier.size(20.dp),
                            tint = MaterialTheme.colorScheme.error
                        )
                    }
                }
            }
        }
    }
}

fun formatDateTimeRange(start: Instant, end: Instant?, allDay: Boolean): String {
    val tz = TimeZone.currentSystemDefault()
    val startLocal = start.toLocalDateTime(tz)

    return if (allDay) {
        "${startLocal.dayOfMonth} ${startLocal.month.name.lowercase().replaceFirstChar { it.uppercase() }} ${startLocal.year}"
    } else {
        val startStr = buildString {
            append("${startLocal.dayOfMonth} ${startLocal.month.name.lowercase().replaceFirstChar { it.uppercase() }}")
            append(" ${startLocal.hour.toString().padStart(2, '0')}:${startLocal.minute.toString().padStart(2, '0')}")
        }

        if (end != null) {
            val endLocal = end.toLocalDateTime(tz)
            val endStr = if (endLocal.date == startLocal.date) {
                "${endLocal.hour.toString().padStart(2, '0')}:${endLocal.minute.toString().padStart(2, '0')}"
            } else {
                "${endLocal.dayOfMonth} ${endLocal.month.name.lowercase().replaceFirstChar { it.uppercase() }} ${endLocal.hour.toString().padStart(2, '0')}:${endLocal.minute.toString().padStart(2, '0')}"
            }
            "$startStr - $endStr"
        } else {
            startStr
        }
    }
}
