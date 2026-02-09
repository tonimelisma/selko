package net.melisma.selko.ui.screens.history

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Cancel
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Undo
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Snackbar
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.datetime.TimeZone
import kotlinx.datetime.toLocalDateTime
import net.melisma.selko.data.model.CalendarEvent
import net.melisma.selko.data.model.EventStatus
import org.koin.androidx.compose.koinViewModel

@Composable
fun HistoryScreen(
    viewModel: HistoryViewModel = koinViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()

    Box(modifier = Modifier.fillMaxSize()) {
        when {
            uiState.isLoading -> {
                CircularProgressIndicator(
                    modifier = Modifier.align(Alignment.Center)
                )
            }

            uiState.allEvents.isEmpty() -> {
                EmptyHistoryContent()
            }

            else -> {
                LazyColumn(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = 16.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    item {
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            text = "Activity History",
                            style = MaterialTheme.typography.headlineSmall,
                            modifier = Modifier.padding(bottom = 8.dp)
                        )
                    }

                    uiState.dateGroups.forEach { group ->
                        item {
                            Text(
                                text = group.dateLabel,
                                style = MaterialTheme.typography.titleSmall,
                                color = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.padding(top = 12.dp, bottom = 4.dp)
                            )
                        }

                        items(group.events, key = { it.id }) { event ->
                            HistoryEventItem(
                                event = event,
                                isProcessing = event.id in uiState.processingEventIds,
                                onUndo = { viewModel.undoEvent(event.id) },
                                onRetry = { viewModel.retrySync(event.id) }
                            )
                        }
                    }

                    if (uiState.hasMore) {
                        item {
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(16.dp),
                                contentAlignment = Alignment.Center
                            ) {
                                if (uiState.isLoadingMore) {
                                    CircularProgressIndicator(modifier = Modifier.size(24.dp))
                                } else {
                                    TextButton(
                                        onClick = { viewModel.loadMore() },
                                        shape = MaterialTheme.shapes.medium
                                    ) {
                                        Text("Load More")
                                    }
                                }
                            }
                        }
                    }

                    item {
                        Spacer(modifier = Modifier.height(16.dp))
                    }
                }
            }
        }

        // Error snackbar
        uiState.errorMessage?.let { error ->
            Snackbar(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .padding(16.dp),
                action = {
                    TextButton(
                        onClick = { viewModel.clearError() },
                        shape = MaterialTheme.shapes.medium
                    ) {
                        Text("Dismiss")
                    }
                }
            ) {
                Text(error)
            }
        }
    }
}

@Composable
private fun HistoryEventItem(
    event: CalendarEvent,
    isProcessing: Boolean,
    onUndo: () -> Unit,
    onRetry: () -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface
        )
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            // Status icon
            StatusIcon(status = event.status)

            Spacer(modifier = Modifier.width(12.dp))

            // Event details
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = event.title,
                    style = MaterialTheme.typography.bodyLarge,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    text = getStatusDescription(event),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                event.updatedAt?.let { updatedAt ->
                    val tz = TimeZone.currentSystemDefault()
                    val local = updatedAt.toLocalDateTime(tz)
                    Text(
                        text = "${local.hour.toString().padStart(2, '0')}:${local.minute.toString().padStart(2, '0')}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
                    )
                }
            }

            // Action button
            if (isProcessing) {
                CircularProgressIndicator(
                    modifier = Modifier.size(24.dp),
                    strokeWidth = 2.dp
                )
            } else {
                when (event.status) {
                    EventStatus.APPROVED, EventStatus.REJECTED, EventStatus.CANCELLED -> {
                        IconButton(onClick = onUndo) {
                            Icon(
                                imageVector = Icons.Filled.Undo,
                                contentDescription = "Undo",
                                tint = MaterialTheme.colorScheme.primary
                            )
                        }
                    }
                    EventStatus.SYNC_FAILED -> {
                        IconButton(onClick = onRetry) {
                            Icon(
                                imageVector = Icons.Filled.Refresh,
                                contentDescription = "Retry",
                                tint = MaterialTheme.colorScheme.primary
                            )
                        }
                    }
                    else -> { /* No action for SYNCED */ }
                }
            }
        }
    }
}

@Composable
private fun StatusIcon(status: EventStatus) {
    val (icon, tint) = when (status) {
        EventStatus.APPROVED -> Icons.Filled.CheckCircle to MaterialTheme.colorScheme.primary
        EventStatus.SYNCED -> Icons.Filled.CheckCircle to Color(0xFF4CAF50)
        EventStatus.SYNC_FAILED -> Icons.Filled.Error to MaterialTheme.colorScheme.error
        EventStatus.REJECTED -> Icons.Filled.Cancel to MaterialTheme.colorScheme.onSurfaceVariant
        EventStatus.CANCELLED -> Icons.Filled.Cancel to MaterialTheme.colorScheme.onSurfaceVariant
        else -> Icons.Filled.History to MaterialTheme.colorScheme.onSurfaceVariant
    }
    Icon(
        imageVector = icon,
        contentDescription = status.name,
        modifier = Modifier.size(24.dp),
        tint = tint
    )
}

private fun getStatusDescription(event: CalendarEvent): String {
    return when (event.status) {
        EventStatus.APPROVED -> "Approved, waiting to sync"
        EventStatus.SYNCED -> "Synced to Google Calendar"
        EventStatus.SYNC_FAILED -> "Sync failed"
        EventStatus.REJECTED -> "Rejected"
        EventStatus.CANCELLED -> "Cancelled"
        else -> event.status.name
    }
}

@Composable
private fun EmptyHistoryContent() {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Icon(
            imageVector = Icons.Filled.History,
            contentDescription = "No activity",
            modifier = Modifier.size(64.dp),
            tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)
        )

        Spacer(modifier = Modifier.height(16.dp))

        Text(
            text = "No Activity Yet",
            style = MaterialTheme.typography.headlineSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )

        Spacer(modifier = Modifier.height(8.dp))

        Text(
            text = "Events you approve or reject will appear here.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
            textAlign = TextAlign.Center
        )
    }
}
