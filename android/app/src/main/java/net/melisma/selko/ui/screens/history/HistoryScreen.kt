package net.melisma.selko.ui.screens.history

import android.content.res.Resources
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.material.icons.automirrored.filled.Undo
import androidx.compose.material.icons.filled.Cancel
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Snackbar
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.datetime.TimeZone
import kotlinx.datetime.toLocalDateTime
import net.melisma.selko.R
import net.melisma.selko.data.model.CalendarEvent
import net.melisma.selko.data.model.EventStatus
import net.melisma.selko.ui.components.SelkoScreenHeader
import net.melisma.selko.ui.components.SelkoActionRole
import net.melisma.selko.ui.components.SelkoButton
import net.melisma.selko.ui.components.SelkoStateTag
import net.melisma.selko.ui.components.SelkoTagRole
import net.melisma.selko.ui.theme.SelkoTheme
import org.koin.androidx.compose.koinViewModel

@Composable
fun HistoryScreen(
    viewModel: HistoryViewModel = koinViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
    ) {
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
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(bottom = 24.dp)
                    ) {
                    item {
                        SelkoScreenHeader(
                            title = stringResource(R.string.history_title),
                            subtitle = stringResource(R.string.history_subtitle)
                        )
                    }

                    uiState.dateGroups.forEach { group ->
                        item {
                            Text(
                                text = group.dateLabel,
                                style = MaterialTheme.typography.titleSmall,
                                color = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.padding(
                                    start = 16.dp,
                                    end = 16.dp,
                                    top = 12.dp,
                                    bottom = 4.dp
                                )
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
                                    SelkoButton(stringResource(R.string.history_load_more), viewModel::loadMore, role = SelkoActionRole.Tertiary)
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
                    if (uiState.canForceUndo) {
                        SelkoButton(stringResource(R.string.history_force_undo), viewModel::forceUndoPendingEvent, role = SelkoActionRole.Tertiary)
                    } else {
                        SelkoButton(stringResource(R.string.history_dismiss), viewModel::clearError, role = SelkoActionRole.Tertiary)
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
    val resources = LocalContext.current.resources

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
        shape = MaterialTheme.shapes.large
    ) {
        ListItem(
            leadingContent = { StatusIcon(status = event.status) },
            headlineContent = {
                Column {
                    SelkoStateTag(
                        text = if (event.isPendingChange) "Changed" else "New",
                        role = if (event.isPendingChange) SelkoTagRole.Changed else SelkoTagRole.New
                    )
                    Text(text = event.title, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            },
            supportingContent = {
                Column {
                    Text(
                        text = getStatusDescription(event, resources),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    event.updatedAt?.let { updatedAt ->
                        val tz = TimeZone.currentSystemDefault()
                        val local = updatedAt.toLocalDateTime(tz)
                        Text(
                            text = "${local.hour.toString().padStart(2, '0')}:${local.minute.toString().padStart(2, '0')}",
                            style = MaterialTheme.typography.bodySmall,
                            color = SelkoTheme.colors.faint
                        )
                    }
                }
            },
            trailingContent = {
                if (isProcessing) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(24.dp),
                        strokeWidth = 2.dp
                    )
                } else {
                    when (event.status) {
                    EventStatus.APPROVED, EventStatus.REJECTED, EventStatus.CANCELLED -> {
                        SelkoButton(
                            stringResource(R.string.history_undo), onUndo,
                            role = SelkoActionRole.Tertiary,
                            icon = Icons.AutoMirrored.Filled.Undo
                        )
                    }
                    EventStatus.SYNC_FAILED -> {
                        SelkoButton(
                            stringResource(R.string.history_retry), onRetry,
                            role = SelkoActionRole.Tertiary,
                            icon = Icons.Filled.Refresh
                        )
                    }
                    EventStatus.SYNCED -> {
                        SelkoButton(
                            stringResource(R.string.history_undo), onUndo,
                            role = SelkoActionRole.Tertiary,
                            icon = Icons.AutoMirrored.Filled.Undo
                        )
                    }
                        else -> { }
                    }
                }
            }
        )
    }
}

@Composable
private fun StatusIcon(status: EventStatus) {
    val (icon, tint) = when (status) {
        EventStatus.APPROVED -> Icons.Filled.CheckCircle to MaterialTheme.colorScheme.primary
        EventStatus.SYNCED -> Icons.Filled.CheckCircle to SelkoTheme.colors.success
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

private fun getStatusDescription(event: CalendarEvent, resources: Resources): String {
    return when (event.status) {
        EventStatus.APPROVED -> resources.getString(R.string.history_status_approved)
        EventStatus.SYNCED -> resources.getString(R.string.history_status_synced)
        EventStatus.SYNC_FAILED -> resources.getString(R.string.history_status_sync_failed)
        EventStatus.REJECTED -> resources.getString(R.string.history_status_rejected)
        EventStatus.CANCELLED -> resources.getString(R.string.history_status_cancelled)
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
            contentDescription = stringResource(R.string.history_empty_icon_description),
            modifier = Modifier.size(64.dp),
            tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)
        )

        Spacer(modifier = Modifier.height(16.dp))

        Text(
            text = stringResource(R.string.history_empty_title),
            style = MaterialTheme.typography.headlineSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )

        Spacer(modifier = Modifier.height(8.dp))

        Text(
            text = stringResource(R.string.history_empty_subtitle),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
            textAlign = TextAlign.Center
        )
    }
}
