package net.melisma.selko.ui.screens.review

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.material3.BottomAppBar
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Snackbar
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.datetime.TimeZone
import kotlinx.datetime.toLocalDateTime
import net.melisma.selko.R
import net.melisma.selko.data.model.SourceOrigin
import net.melisma.selko.ui.theme.SelkoTheme
import org.koin.androidx.compose.koinViewModel
import org.koin.core.parameter.parametersOf
import kotlin.time.Instant

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EventDetailScreen(
    eventId: String,
    onNavigateBack: () -> Unit,
    viewModel: EventDetailViewModel = koinViewModel { parametersOf(eventId) }
) {
    val uiState by viewModel.uiState.collectAsState()

    // Navigate back when done (approved/rejected)
    LaunchedEffect(uiState.isDone) {
        if (uiState.isDone) {
            onNavigateBack()
        }
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.event_detail_title)) },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface
                ),
                navigationIcon = {
                    IconButton(onClick = {
                        if (uiState.hasUnsavedChanges) {
                            viewModel.saveChanges()
                        }
                        onNavigateBack()
                    }) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = stringResource(R.string.event_detail_back)
                        )
                    }
                }
            )
        },
        bottomBar = {
            if (!uiState.isLoading && uiState.event != null) {
                BottomAppBar(
                    containerColor = MaterialTheme.colorScheme.surface,
                    tonalElevation = 0.dp
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 16.dp),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        OutlinedButton(
                            onClick = { viewModel.rejectEvent() },
                            enabled = !uiState.isRejecting && !uiState.isApproving,
                            colors = ButtonDefaults.outlinedButtonColors(
                                contentColor = MaterialTheme.colorScheme.error
                            ),
                            border = BorderStroke(1.dp, MaterialTheme.colorScheme.error),
                            shape = MaterialTheme.shapes.medium
                        ) {
                            if (uiState.isRejecting) {
                                CircularProgressIndicator(
                                    modifier = Modifier.size(18.dp),
                                    strokeWidth = 2.dp
                                )
                            } else {
                                Icon(
                                    imageVector = Icons.Filled.Close,
                                    contentDescription = stringResource(R.string.event_detail_reject),
                                    modifier = Modifier.size(18.dp)
                                )
                            }
                            Spacer(modifier = Modifier.width(4.dp))
                            Text(stringResource(R.string.event_detail_reject))
                        }

                        Button(
                            onClick = { viewModel.approveEvent() },
                            enabled = !uiState.isApproving && !uiState.isRejecting,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = SelkoTheme.colors.success,
                                contentColor = SelkoTheme.colors.onSuccess
                            ),
                            shape = MaterialTheme.shapes.medium
                        ) {
                            if (uiState.isApproving) {
                                CircularProgressIndicator(
                                    modifier = Modifier.size(18.dp),
                                    strokeWidth = 2.dp,
                                    color = SelkoTheme.colors.onSuccess
                                )
                            } else {
                                Icon(
                                    imageVector = Icons.Filled.Check,
                                    contentDescription = stringResource(R.string.event_detail_accept),
                                    modifier = Modifier.size(18.dp)
                                )
                            }
                            Spacer(modifier = Modifier.width(4.dp))
                            Text(stringResource(R.string.event_detail_accept))
                        }
                    }
                }
            }
        }
    ) { paddingValues ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background)
                .padding(paddingValues)
        ) {
            when {
                uiState.isLoading -> {
                    CircularProgressIndicator(
                        modifier = Modifier.align(Alignment.Center)
                    )
                }

                uiState.event == null -> {
                    Text(
                        text = uiState.errorMessage ?: stringResource(R.string.event_detail_not_found),
                        modifier = Modifier
                            .align(Alignment.Center)
                            .padding(16.dp),
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.error
                    )
                }

                else -> {
                    EventDetailContent(
                        uiState = uiState,
                        onTitleChange = viewModel::onTitleChange,
                        onStartDateChange = viewModel::onStartDateChange,
                        onStartTimeChange = viewModel::onStartTimeChange,
                        onEndDateChange = viewModel::onEndDateChange,
                        onEndTimeChange = viewModel::onEndTimeChange,
                        onLocationChange = viewModel::onLocationChange,
                        onDescriptionChange = viewModel::onDescriptionChange,
                        onAllDayChange = viewModel::onAllDayChange
                    )
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
                            Text(stringResource(R.string.event_detail_dismiss))
                        }
                    }
                ) {
                    Text(error)
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun EventDetailContent(
    uiState: EventDetailUiState,
    onTitleChange: (String) -> Unit,
    onStartDateChange: (Long) -> Unit,
    onStartTimeChange: (Int, Int) -> Unit,
    onEndDateChange: (Long) -> Unit,
    onEndTimeChange: (Int, Int) -> Unit,
    onLocationChange: (String) -> Unit,
    onDescriptionChange: (String) -> Unit,
    onAllDayChange: (Boolean) -> Unit
) {
    var showStartDatePicker by remember { mutableStateOf(false) }
    var showStartTimePicker by remember { mutableStateOf(false) }
    var showEndDatePicker by remember { mutableStateOf(false) }
    var showEndTimePicker by remember { mutableStateOf(false) }

    val tz = TimeZone.currentSystemDefault()
    val selectDateText = stringResource(R.string.event_detail_select_date)
    val selectTimeText = stringResource(R.string.event_detail_select_time)

    fun formatDate(instant: Instant?): String {
        if (instant == null) return selectDateText
        val local = instant.toLocalDateTime(tz)
        return "${local.day} ${local.month.name.lowercase().replaceFirstChar { it.uppercase() }} ${local.year}"
    }

    fun formatTime(instant: Instant?): String {
        if (instant == null) return selectTimeText
        val local = instant.toLocalDateTime(tz)
        return "${local.hour.toString().padStart(2, '0')}:${local.minute.toString().padStart(2, '0')}"
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp)
    ) {
        // Source section
        when (uiState.sourceOrigin) {
            SourceOrigin.GOOGLE_PHOTOS -> {
                SourcePhotoCard()
                Spacer(modifier = Modifier.height(16.dp))
            }
            else -> {
                uiState.sourceEmail?.let { email ->
                    SourceEmailCard(email = email)
                    Spacer(modifier = Modifier.height(16.dp))
                }
            }
        }

        // Event form fields
        OutlinedTextField(
            value = uiState.title,
            onValueChange = onTitleChange,
            label = { Text(stringResource(R.string.event_detail_field_title)) },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            shape = MaterialTheme.shapes.small
        )

        Spacer(modifier = Modifier.height(12.dp))

        // Start Date
        OutlinedTextField(
            value = formatDate(uiState.startInstant),
            onValueChange = {},
            readOnly = true,
            label = { Text(if (uiState.allDay) stringResource(R.string.event_detail_field_date) else stringResource(R.string.event_detail_field_start_date)) },
            modifier = Modifier.fillMaxWidth().clickable { showStartDatePicker = true },
            enabled = false,
            colors = OutlinedTextFieldDefaults.colors(
                disabledTextColor = MaterialTheme.colorScheme.onSurface,
                disabledBorderColor = MaterialTheme.colorScheme.outline,
                disabledLabelColor = MaterialTheme.colorScheme.onSurfaceVariant
            ),
            shape = MaterialTheme.shapes.small
        )

        Spacer(modifier = Modifier.height(12.dp))

        if (!uiState.allDay) {
            // Start Time
            OutlinedTextField(
                value = formatTime(uiState.startInstant),
                onValueChange = {},
                readOnly = true,
                label = { Text(stringResource(R.string.event_detail_field_start_time)) },
                modifier = Modifier.fillMaxWidth().clickable { showStartTimePicker = true },
                enabled = false,
                colors = OutlinedTextFieldDefaults.colors(
                    disabledTextColor = MaterialTheme.colorScheme.onSurface,
                    disabledBorderColor = MaterialTheme.colorScheme.outline,
                    disabledLabelColor = MaterialTheme.colorScheme.onSurfaceVariant
                ),
                shape = MaterialTheme.shapes.small
            )

            Spacer(modifier = Modifier.height(12.dp))
        }

        // End Date
        OutlinedTextField(
            value = formatDate(uiState.endInstant),
            onValueChange = {},
            readOnly = true,
            label = { Text(stringResource(R.string.event_detail_field_end_date)) },
            modifier = Modifier.fillMaxWidth().clickable { showEndDatePicker = true },
            enabled = false,
            colors = OutlinedTextFieldDefaults.colors(
                disabledTextColor = MaterialTheme.colorScheme.onSurface,
                disabledBorderColor = MaterialTheme.colorScheme.outline,
                disabledLabelColor = MaterialTheme.colorScheme.onSurfaceVariant
            ),
            shape = MaterialTheme.shapes.small
        )

        Spacer(modifier = Modifier.height(12.dp))

        if (!uiState.allDay) {
            // End Time
            OutlinedTextField(
                value = formatTime(uiState.endInstant),
                onValueChange = {},
                readOnly = true,
                label = { Text(stringResource(R.string.event_detail_field_end_time)) },
                modifier = Modifier.fillMaxWidth().clickable { showEndTimePicker = true },
                enabled = false,
                colors = OutlinedTextFieldDefaults.colors(
                    disabledTextColor = MaterialTheme.colorScheme.onSurface,
                    disabledBorderColor = MaterialTheme.colorScheme.outline,
                    disabledLabelColor = MaterialTheme.colorScheme.onSurfaceVariant
                ),
                shape = MaterialTheme.shapes.small
            )

            Spacer(modifier = Modifier.height(12.dp))
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = stringResource(R.string.event_detail_all_day),
                style = MaterialTheme.typography.bodyLarge
            )
            Switch(
                checked = uiState.allDay,
                onCheckedChange = onAllDayChange
            )
        }

        Spacer(modifier = Modifier.height(12.dp))

        OutlinedTextField(
            value = uiState.location,
            onValueChange = onLocationChange,
            label = { Text(stringResource(R.string.event_detail_field_location)) },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            shape = MaterialTheme.shapes.small
        )

        Spacer(modifier = Modifier.height(12.dp))

        OutlinedTextField(
            value = uiState.description,
            onValueChange = onDescriptionChange,
            label = { Text(stringResource(R.string.event_detail_field_description)) },
            modifier = Modifier.fillMaxWidth(),
            minLines = 3,
            maxLines = 6,
            shape = MaterialTheme.shapes.small
        )

        // Source attribution
        uiState.event?.sourceAttribution?.let { attribution ->
            Spacer(modifier = Modifier.height(16.dp))
            Text(
                text = stringResource(R.string.event_detail_source_label, attribution),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }

        Spacer(modifier = Modifier.height(80.dp)) // Space for bottom bar

        // Date/Time Picker Dialogs
        if (showStartDatePicker) {
            val datePickerState = rememberDatePickerState(
                initialSelectedDateMillis = uiState.startInstant?.toEpochMilliseconds()
            )
            DatePickerDialog(
                onDismissRequest = { showStartDatePicker = false },
                confirmButton = {
                    TextButton(onClick = {
                        datePickerState.selectedDateMillis?.let { onStartDateChange(it) }
                        showStartDatePicker = false
                    }) { Text(stringResource(R.string.event_detail_ok)) }
                },
                dismissButton = {
                    TextButton(onClick = { showStartDatePicker = false }) { Text(stringResource(R.string.event_detail_cancel)) }
                }
            ) {
                DatePicker(state = datePickerState)
            }
        }

        if (showStartTimePicker) {
            val startLocal = uiState.startInstant?.toLocalDateTime(tz)
            val timePickerState = rememberTimePickerState(
                initialHour = startLocal?.hour ?: 9,
                initialMinute = startLocal?.minute ?: 0
            )
            DatePickerDialog(
                onDismissRequest = { showStartTimePicker = false },
                confirmButton = {
                    TextButton(onClick = {
                        onStartTimeChange(timePickerState.hour, timePickerState.minute)
                        showStartTimePicker = false
                    }) { Text(stringResource(R.string.event_detail_ok)) }
                },
                dismissButton = {
                    TextButton(onClick = { showStartTimePicker = false }) { Text(stringResource(R.string.event_detail_cancel)) }
                }
            ) {
                TimePicker(state = timePickerState)
            }
        }

        if (showEndDatePicker) {
            val datePickerState = rememberDatePickerState(
                initialSelectedDateMillis = uiState.endInstant?.toEpochMilliseconds()
            )
            DatePickerDialog(
                onDismissRequest = { showEndDatePicker = false },
                confirmButton = {
                    TextButton(onClick = {
                        datePickerState.selectedDateMillis?.let { onEndDateChange(it) }
                        showEndDatePicker = false
                    }) { Text(stringResource(R.string.event_detail_ok)) }
                },
                dismissButton = {
                    TextButton(onClick = { showEndDatePicker = false }) { Text(stringResource(R.string.event_detail_cancel)) }
                }
            ) {
                DatePicker(state = datePickerState)
            }
        }

        if (showEndTimePicker) {
            val endLocal = uiState.endInstant?.toLocalDateTime(tz)
            val timePickerState = rememberTimePickerState(
                initialHour = endLocal?.hour ?: 10,
                initialMinute = endLocal?.minute ?: 0
            )
            DatePickerDialog(
                onDismissRequest = { showEndTimePicker = false },
                confirmButton = {
                    TextButton(onClick = {
                        onEndTimeChange(timePickerState.hour, timePickerState.minute)
                        showEndTimePicker = false
                    }) { Text(stringResource(R.string.event_detail_ok)) }
                },
                dismissButton = {
                    TextButton(onClick = { showEndTimePicker = false }) { Text(stringResource(R.string.event_detail_cancel)) }
                }
            ) {
                TimePicker(state = timePickerState)
            }
        }
    }
}

@Composable
private fun SourcePhotoCard() {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = Icons.Filled.PhotoCamera,
                contentDescription = stringResource(R.string.source_photo_icon_description),
                modifier = Modifier.size(20.dp),
                tint = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                text = stringResource(R.string.source_photo_label),
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
private fun SourceEmailCard(email: net.melisma.selko.data.model.Email) {
    var isExpanded by remember { mutableStateOf(false) }

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.weight(1f)
                ) {
                    Icon(
                        imageVector = Icons.Filled.Email,
                        contentDescription = stringResource(R.string.source_email_icon_description),
                        modifier = Modifier.size(20.dp),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        text = stringResource(R.string.source_email_label),
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                IconButton(onClick = { isExpanded = !isExpanded }) {
                    Icon(
                        imageVector = if (isExpanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                        contentDescription = if (isExpanded) stringResource(R.string.source_email_collapse) else stringResource(R.string.source_email_expand)
                    )
                }
            }

            AnimatedVisibility(visible = isExpanded) {
                Column {
                    Spacer(modifier = Modifier.height(8.dp))

                    Text(
                        text = stringResource(R.string.source_email_from, email.displaySender),
                        style = MaterialTheme.typography.bodyMedium
                    )

                    email.fromEmail?.let {
                        Text(
                            text = it,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }

                    email.subject?.let { subject ->
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = stringResource(R.string.source_email_subject, subject),
                            style = MaterialTheme.typography.bodyMedium,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis
                        )
                    }

                    email.dateSent?.let { date ->
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = stringResource(R.string.source_email_sent, date.toString()),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }
        }
    }
}
