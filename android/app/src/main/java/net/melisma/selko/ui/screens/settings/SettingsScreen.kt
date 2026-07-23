package net.melisma.selko.ui.screens.settings

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
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
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Block
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuAnchorType
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Snackbar
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.foundation.clickable
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.TimePicker
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import net.melisma.selko.R
import net.melisma.selko.data.model.IntegrationProvider
import net.melisma.selko.data.model.IntegrationStatus
import net.melisma.selko.data.model.SenderRule
import net.melisma.selko.data.repository.AllDayDisplayMode
import net.melisma.selko.ui.components.SelkoScreenHeader
import net.melisma.selko.ui.components.SelkoActionRole
import net.melisma.selko.ui.components.SelkoButton
import net.melisma.selko.ui.components.SelkoIconButton
import net.melisma.selko.ui.components.SelkoLabeledSwitch
import net.melisma.selko.ui.components.SelkoStatusIndicator
import net.melisma.selko.ui.theme.SelkoTheme
import org.koin.androidx.compose.koinViewModel

@Composable
fun SettingsScreen(
    onLogout: () -> Unit,
    viewModel: SettingsViewModel = koinViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
    ) {
        if (uiState.isLoading) {
            CircularProgressIndicator(
                modifier = Modifier.align(Alignment.Center)
            )
        } else {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(bottom = 24.dp)
            ) {
                SelkoScreenHeader(
                    title = stringResource(R.string.settings_title),
                    subtitle = stringResource(R.string.settings_subtitle),
                    email = uiState.userEmail,
                    modifier = Modifier.padding(horizontal = 0.dp)
                )

                Spacer(modifier = Modifier.height(24.dp))

                // Sections get the screen gutter; the header brings its own.
                Column(modifier = Modifier.padding(horizontal = 16.dp)) {
                    // Connected Accounts Section
                    SectionHeader(title = stringResource(R.string.settings_section_connected_accounts))
                    Spacer(modifier = Modifier.height(8.dp))
                    ConnectedAccountsSection(
                        uiState = uiState,
                        onDisconnect = { viewModel.disconnectIntegration(it) },
                        gmailAuthUrl = viewModel.getGmailAuthUrl(),
                        outlookAuthUrl = viewModel.getOutlookAuthUrl(),
                        calendarAuthUrl = viewModel.getCalendarAuthUrl()
                    )

                    Spacer(modifier = Modifier.height(24.dp))

                    EmailFoldersSection(
                        uiState = uiState,
                        onToggle = viewModel::updateEmailFolder,
                        onRetryLoad = viewModel::loadEmailFolders,
                        onRetryUpdate = viewModel::retryEmailFolder
                    )

                    Spacer(modifier = Modifier.height(24.dp))

                    // Calendar Defaults Section
                    SectionHeader(title = stringResource(R.string.settings_section_calendar_defaults))
                    Spacer(modifier = Modifier.height(8.dp))
                    CalendarDefaultsSection(
                        uiState = uiState,
                        onCalendarSelected = { viewModel.onCalendarSelected(it) },
                        onDefaultInviteesChange = { viewModel.onDefaultInviteesChange(it) },
                        onSaveInvitees = { viewModel.saveCalendarSettings() },
                        onAllDayDisplayModeChange = { viewModel.onAllDayDisplayModeChange(it) },
                        onAllDayCustomStartChange = { h, m -> viewModel.onAllDayCustomStartChange(h, m) },
                        onAllDayCustomEndChange = { h, m -> viewModel.onAllDayCustomEndChange(h, m) },
                        allDayPreviewWindow = viewModel.allDayPreviewWindow()
                    )

                    Spacer(modifier = Modifier.height(24.dp))

                    // Automation Rules Section
                    SectionHeader(title = stringResource(R.string.settings_section_automation_rules))
                    Spacer(modifier = Modifier.height(8.dp))
                    AutomationRulesSection(
                        rules = uiState.rules,
                        isLoading = uiState.isLoadingRules,
                        onCreateRule = { senderEmail, senderDomain, action ->
                            viewModel.createRule(senderEmail, senderDomain, action)
                        },
                        onDeleteRule = { viewModel.deleteRule(it) }
                    )

                    Spacer(modifier = Modifier.height(24.dp))

                    // Account Section
                    SectionHeader(title = stringResource(R.string.settings_section_account))
                    Spacer(modifier = Modifier.height(8.dp))
                    AccountSection(
                        uiState = uiState,
                        onSignOut = { viewModel.signOut(onLogout) }
                    )

                    Spacer(modifier = Modifier.height(32.dp))
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
                    SelkoButton(stringResource(R.string.settings_dismiss), viewModel::clearError, role = SelkoActionRole.Tertiary)
                }
            ) {
                Text(error)
            }
        }
    }
}

@Composable
private fun SectionHeader(title: String) {
    Text(
        text = title.uppercase(),
        style = MaterialTheme.typography.labelMedium,
        color = SelkoTheme.colors.faint
    )
}

@Composable
private fun ConnectedAccountsSection(
    uiState: SettingsUiState,
    onDisconnect: (IntegrationProvider) -> Unit,
    gmailAuthUrl: String,
    outlookAuthUrl: String,
    calendarAuthUrl: String
) {
    val context = LocalContext.current
    val gmailIntegration = uiState.integrations.find { it.provider == IntegrationProvider.GMAIL }
    val outlookIntegration = uiState.integrations.find { it.provider == IntegrationProvider.OUTLOOK }
    val calendarIntegration = uiState.integrations.find { it.provider == IntegrationProvider.GOOGLE_CALENDAR }

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
        shape = MaterialTheme.shapes.large
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            // Gmail
            IntegrationRow(
                icon = Icons.Filled.Email,
                label = stringResource(R.string.settings_gmail),
                email = gmailIntegration?.providerEmail,
                isConnected = gmailIntegration?.status == IntegrationStatus.ACTIVE,
                isDisconnecting = uiState.isDisconnecting,
                onConnect = {
                    try {
                        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(gmailAuthUrl))
                        context.startActivity(intent)
                    } catch (_: android.content.ActivityNotFoundException) {
                        // No browser available
                    }
                },
                onDisconnect = { onDisconnect(IntegrationProvider.GMAIL) }
            )

            HorizontalDivider(modifier = Modifier.padding(vertical = 8.dp))

            // Outlook
            IntegrationRow(
                icon = Icons.Filled.Email,
                label = stringResource(R.string.settings_outlook),
                email = outlookIntegration?.providerEmail,
                isConnected = outlookIntegration?.status == IntegrationStatus.ACTIVE,
                isDisconnecting = uiState.isDisconnecting,
                onConnect = {
                    try {
                        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(outlookAuthUrl))
                        context.startActivity(intent)
                    } catch (_: android.content.ActivityNotFoundException) {
                        // No browser available
                    }
                },
                onDisconnect = { onDisconnect(IntegrationProvider.OUTLOOK) }
            )

            HorizontalDivider(modifier = Modifier.padding(vertical = 8.dp))

            // Google Calendar
            IntegrationRow(
                icon = Icons.Filled.CalendarMonth,
                label = stringResource(R.string.settings_google_calendar),
                email = calendarIntegration?.providerEmail,
                isConnected = calendarIntegration?.status == IntegrationStatus.ACTIVE,
                isDisconnecting = uiState.isDisconnecting,
                onConnect = {
                    try {
                        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(calendarAuthUrl))
                        context.startActivity(intent)
                    } catch (_: android.content.ActivityNotFoundException) {
                        // No browser available
                    }
                },
                onDisconnect = { onDisconnect(IntegrationProvider.GOOGLE_CALENDAR) }
            )
        }
    }
}

@Composable
private fun IntegrationRow(
    icon: ImageVector,
    label: String,
    email: String?,
    isConnected: Boolean,
    isDisconnecting: Boolean,
    onConnect: () -> Unit,
    onDisconnect: () -> Unit
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
                imageVector = icon,
                contentDescription = label,
                modifier = Modifier.size(24.dp),
                tint = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(modifier = Modifier.width(12.dp))
            Column {
                Text(
                    text = label,
                    style = MaterialTheme.typography.bodyLarge
                )
                if (isConnected && email != null) {
                    Text(
                        text = email,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }

        if (isConnected) {
            Column(horizontalAlignment = Alignment.End) {
                SelkoStatusIndicator(
                    text = stringResource(R.string.settings_connected),
                    icon = Icons.Filled.CheckCircle,
                    color = SelkoTheme.colors.successText
                )
                SelkoButton(
                    text = stringResource(R.string.settings_disconnect),
                    onClick = onDisconnect,
                    role = SelkoActionRole.DestructiveOutline,
                    enabled = !isDisconnecting,
                    loading = isDisconnecting
                )
            }
        } else {
            SelkoButton(stringResource(R.string.settings_connect), onConnect, role = SelkoActionRole.Secondary)
        }
    }
}

@Composable
private fun EmailFoldersSection(
    uiState: SettingsUiState,
    onToggle: (IntegrationProvider, String, Boolean) -> Unit,
    onRetryLoad: (IntegrationProvider) -> Unit,
    onRetryUpdate: (IntegrationProvider, String) -> Unit
) {
    val connected = listOf(IntegrationProvider.GMAIL, IntegrationProvider.OUTLOOK).filter { provider ->
        uiState.integrations.any { it.provider == provider && it.status == IntegrationStatus.ACTIVE }
    }
    if (connected.isEmpty()) return
    SectionHeader("Email Folders")
    Spacer(Modifier.height(8.dp))
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
        shape = MaterialTheme.shapes.large
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            connected.forEach { provider ->
                Text(if (provider == IntegrationProvider.GMAIL) "Gmail" else "Outlook", style = MaterialTheme.typography.titleMedium)
                when {
                    provider in uiState.loadingFolderProviders -> CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp)
                    uiState.folderLoadErrors[provider] != null -> Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(uiState.folderLoadErrors.getValue(provider), color = MaterialTheme.colorScheme.error, modifier = Modifier.weight(1f))
                        SelkoButton("Retry", { onRetryLoad(provider) }, role = SelkoActionRole.Tertiary)
                    }
                    else -> uiState.emailFolders[provider].orEmpty().forEach { folder ->
                        Column {
                            SelkoLabeledSwitch(
                                title = folder.fullPath,
                                checked = folder.isIncluded,
                                onCheckedChange = { onToggle(provider, folder.id, it) },
                                supportingText = folder.classificationReason?.let { "Recommendation: $it" },
                                enabled = folder.id !in uiState.updatingFolderIds,
                                modifier = Modifier.fillMaxWidth()
                            )
                            if (folder.id in uiState.updatingFolderIds) {
                                CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                            }
                            uiState.folderUpdateErrors[folder.id]?.let { failure ->
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(failure.message, color = MaterialTheme.colorScheme.error, modifier = Modifier.weight(1f))
                                    SelkoButton("Retry", { onRetryUpdate(provider, folder.id) }, role = SelkoActionRole.Tertiary)
                                }
                            }
                        }
                    }
                }
                if (provider != connected.last()) HorizontalDivider()
            }
            Text("Included folders are scanned for calendar-relevant messages.", style = MaterialTheme.typography.bodySmall, color = SelkoTheme.colors.faint)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CalendarDefaultsSection(
    uiState: SettingsUiState,
    onCalendarSelected: (String) -> Unit,
    onDefaultInviteesChange: (String) -> Unit,
    onSaveInvitees: () -> Unit,
    onAllDayDisplayModeChange: (AllDayDisplayMode) -> Unit,
    onAllDayCustomStartChange: (Int, Int) -> Unit,
    onAllDayCustomEndChange: (Int, Int) -> Unit,
    allDayPreviewWindow: String
) {
    var modeExpanded by remember { mutableStateOf(false) }
    var showStartTimePicker by remember { mutableStateOf(false) }
    var showEndTimePicker by remember { mutableStateOf(false) }

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
        shape = MaterialTheme.shapes.large
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            // Calendar picker
            if (uiState.calendars.isNotEmpty()) {
                var expanded by remember { mutableStateOf(false) }
                val selectedCalendar = uiState.calendars.find { it.id == uiState.selectedCalendarId }

                Text(
                    text = stringResource(R.string.settings_target_calendar),
                    style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier.padding(bottom = 4.dp)
                )

                ExposedDropdownMenuBox(
                    expanded = expanded,
                    onExpandedChange = { expanded = !expanded }
                ) {
                    OutlinedTextField(
                        value = selectedCalendar?.name ?: stringResource(R.string.settings_select_calendar),
                        onValueChange = {},
                        readOnly = true,
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable),
                        shape = MaterialTheme.shapes.medium
                    )

                    ExposedDropdownMenu(
                        expanded = expanded,
                        onDismissRequest = { expanded = false }
                    ) {
                        uiState.calendars.forEach { calendar ->
                            DropdownMenuItem(
                                text = {
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        Text(calendar.name)
                                        if (calendar.is_primary) {
                                            Spacer(modifier = Modifier.width(4.dp))
                                            Text(
                                                text = stringResource(R.string.settings_primary_label),
                                                style = MaterialTheme.typography.bodySmall,
                                                color = MaterialTheme.colorScheme.onSurfaceVariant
                                            )
                                        }
                                    }
                                },
                                onClick = {
                                    onCalendarSelected(calendar.id)
                                    expanded = false
                                }
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))
            } else {
                Text(
                    text = stringResource(R.string.settings_connect_calendar_prompt),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(modifier = Modifier.height(16.dp))
            }

            Text(
                text = stringResource(R.string.settings_date_only_events),
                style = MaterialTheme.typography.labelLarge,
                modifier = Modifier.padding(bottom = 4.dp)
            )
            Text(
                text = stringResource(R.string.settings_date_only_events_hint),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(bottom = 8.dp)
            )

            val modeLabel = when (uiState.allDayDisplayMode) {
                AllDayDisplayMode.ALL_DAY -> stringResource(R.string.settings_date_only_all_day)
                AllDayDisplayMode.DAY_9_TO_5 -> stringResource(R.string.settings_date_only_day_9_to_5)
                AllDayDisplayMode.MORNING_8_TO_9 -> stringResource(R.string.settings_date_only_morning_8_to_9)
                AllDayDisplayMode.CUSTOM -> stringResource(R.string.settings_date_only_custom)
            }

            ExposedDropdownMenuBox(
                expanded = modeExpanded,
                onExpandedChange = { modeExpanded = !modeExpanded }
            ) {
                OutlinedTextField(
                    value = modeLabel,
                    onValueChange = {},
                    readOnly = true,
                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = modeExpanded) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable),
                    shape = MaterialTheme.shapes.medium
                )
                ExposedDropdownMenu(
                    expanded = modeExpanded,
                    onDismissRequest = { modeExpanded = false }
                ) {
                    AllDayDisplayMode.entries.forEach { mode ->
                        val label = when (mode) {
                            AllDayDisplayMode.ALL_DAY -> stringResource(R.string.settings_date_only_all_day)
                            AllDayDisplayMode.DAY_9_TO_5 -> stringResource(R.string.settings_date_only_day_9_to_5)
                            AllDayDisplayMode.MORNING_8_TO_9 -> stringResource(R.string.settings_date_only_morning_8_to_9)
                            AllDayDisplayMode.CUSTOM -> stringResource(R.string.settings_date_only_custom)
                        }
                        DropdownMenuItem(
                            text = { Text(label) },
                            onClick = {
                                onAllDayDisplayModeChange(mode)
                                modeExpanded = false
                            }
                        )
                    }
                }
            }

            if (uiState.allDayDisplayMode == AllDayDisplayMode.CUSTOM) {
                Spacer(modifier = Modifier.height(12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .clickable { showStartTimePicker = true }
                    ) {
                        OutlinedTextField(
                            value = stringResource(
                                R.string.settings_date_only_time_format,
                                uiState.allDayCustomStartHour,
                                uiState.allDayCustomStartMinute
                            ),
                            onValueChange = {},
                            readOnly = true,
                            label = { Text(stringResource(R.string.settings_date_only_custom_start)) },
                            modifier = Modifier.fillMaxWidth(),
                            shape = MaterialTheme.shapes.medium
                        )
                    }
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .clickable { showEndTimePicker = true }
                    ) {
                        OutlinedTextField(
                            value = stringResource(
                                R.string.settings_date_only_time_format,
                                uiState.allDayCustomEndHour,
                                uiState.allDayCustomEndMinute
                            ),
                            onValueChange = {},
                            readOnly = true,
                            label = { Text(stringResource(R.string.settings_date_only_custom_end)) },
                            modifier = Modifier.fillMaxWidth(),
                            shape = MaterialTheme.shapes.medium
                        )
                    }
                }
                uiState.allDayCustomError?.let { err ->
                    Text(
                        text = err,
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(top = 8.dp)
                    )
                }
            }

            Text(
                text = stringResource(R.string.settings_date_only_preview, allDayPreviewWindow),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 12.dp)
            )

            Spacer(modifier = Modifier.height(16.dp))

            // Default invitees
            OutlinedTextField(
                value = uiState.defaultInvitees,
                onValueChange = onDefaultInviteesChange,
                label = { Text(stringResource(R.string.settings_default_invitees)) },
                placeholder = { Text(stringResource(R.string.settings_default_invitees_placeholder)) },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                shape = MaterialTheme.shapes.medium
            )

            if (uiState.defaultInvitees.isNotBlank()) {
                Spacer(modifier = Modifier.height(8.dp))
                SelkoButton(
                    stringResource(R.string.settings_save), onSaveInvitees,
                    role = SelkoActionRole.Tertiary,
                    enabled = !uiState.isSavingCalendarSettings,
                    loading = uiState.isSavingCalendarSettings
                )
            }
        }
    }

    if (showStartTimePicker) {
        val timePickerState = rememberTimePickerState(
            initialHour = uiState.allDayCustomStartHour,
            initialMinute = uiState.allDayCustomStartMinute
        )
        DatePickerDialog(
            onDismissRequest = { showStartTimePicker = false },
            confirmButton = {
                SelkoButton(stringResource(R.string.settings_save), onClick = {
                    onAllDayCustomStartChange(timePickerState.hour, timePickerState.minute)
                    showStartTimePicker = false
                }, role = SelkoActionRole.Primary)
            },
            dismissButton = {
                SelkoButton(stringResource(R.string.settings_dismiss), {
                    showStartTimePicker = false
                }, role = SelkoActionRole.Tertiary)
            }
        ) {
            TimePicker(state = timePickerState)
        }
    }

    if (showEndTimePicker) {
        val timePickerState = rememberTimePickerState(
            initialHour = uiState.allDayCustomEndHour,
            initialMinute = uiState.allDayCustomEndMinute
        )
        DatePickerDialog(
            onDismissRequest = { showEndTimePicker = false },
            confirmButton = {
                SelkoButton(stringResource(R.string.settings_save), onClick = {
                    onAllDayCustomEndChange(timePickerState.hour, timePickerState.minute)
                    showEndTimePicker = false
                }, role = SelkoActionRole.Primary)
            },
            dismissButton = {
                SelkoButton(stringResource(R.string.settings_dismiss), {
                    showEndTimePicker = false
                }, role = SelkoActionRole.Tertiary)
            }
        ) {
            TimePicker(state = timePickerState)
        }
    }
}

@Composable
private fun AccountSection(
    uiState: SettingsUiState,
    onSignOut: () -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
        shape = MaterialTheme.shapes.large
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            // User email
            Row(
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(
                    imageVector = Icons.Filled.Person,
                    contentDescription = stringResource(R.string.settings_account_description),
                    modifier = Modifier.size(24.dp),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(modifier = Modifier.width(12.dp))
                Column {
                    Text(
                        text = stringResource(R.string.settings_signed_in_as),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Text(
                        text = uiState.userEmail ?: stringResource(R.string.settings_unknown_user),
                        style = MaterialTheme.typography.bodyLarge
                    )
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            // Log out button
            SelkoButton(
                text = stringResource(R.string.settings_log_out),
                onClick = onSignOut,
                modifier = Modifier.fillMaxWidth(),
                role = SelkoActionRole.DestructiveOutline,
                enabled = !uiState.isSigningOut,
                loading = uiState.isSigningOut,
                icon = Icons.AutoMirrored.Filled.Logout
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AutomationRulesSection(
    rules: List<SenderRule>,
    isLoading: Boolean,
    onCreateRule: (senderEmail: String?, senderDomain: String?, action: String) -> Unit,
    onDeleteRule: (String) -> Unit
) {
    var ruleInput by remember { mutableStateOf("") }
    var selectedAction by remember { mutableStateOf("ignore") }
    var actionExpanded by remember { mutableStateOf(false) }
    var ruleToDelete by remember { mutableStateOf<SenderRule?>(null) }

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
        shape = MaterialTheme.shapes.large
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            if (isLoading) {
                CircularProgressIndicator(
                    modifier = Modifier
                        .size(24.dp)
                        .align(Alignment.CenterHorizontally)
                )
            } else if (rules.isEmpty()) {
                Text(
                    text = stringResource(R.string.settings_rules_empty),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            } else {
                val groups = listOf(
                    Triple("Auto-approved", "auto_approve", Icons.Filled.CheckCircle),
                    Triple("Ignored", "ignore", Icons.Filled.Block)
                )
                groups.forEach { (heading, action, groupIcon) ->
                    val groupRules = rules.filter { it.action == action }
                    if (groupRules.isNotEmpty()) {
                        Text(heading, style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 4.dp, bottom = 4.dp))
                        groupRules.forEach { rule ->
                            Row(
                                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Icon(
                                    imageVector = groupIcon,
                                    contentDescription = null,
                                    modifier = Modifier.size(20.dp),
                                    tint = if (action == "ignore") MaterialTheme.colorScheme.error else SelkoTheme.colors.successText
                                )
                                Spacer(modifier = Modifier.width(12.dp))
                                Text(
                                    text = rule.senderEmail ?: rule.senderDomain ?: stringResource(R.string.settings_rule_unknown_sender),
                                    style = MaterialTheme.typography.bodyMedium,
                                    modifier = Modifier.weight(1f)
                                )
                                SelkoIconButton(
                                    icon = Icons.Filled.Delete,
                                    contentDescription = stringResource(R.string.settings_rule_delete_description),
                                    onClick = { ruleToDelete = rule },
                                    destructive = true
                                )
                            }
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(16.dp))
            HorizontalDivider()
            Spacer(modifier = Modifier.height(12.dp))

            Text(
                text = stringResource(R.string.settings_add_rule_title),
                style = MaterialTheme.typography.labelLarge,
                modifier = Modifier.padding(bottom = 8.dp)
            )

            OutlinedTextField(
                value = ruleInput,
                onValueChange = { ruleInput = it },
                label = { Text(stringResource(R.string.settings_add_rule_email_label)) },
                placeholder = { Text(stringResource(R.string.settings_add_rule_email_placeholder)) },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                shape = MaterialTheme.shapes.medium
            )

            Spacer(modifier = Modifier.height(8.dp))

            ExposedDropdownMenuBox(
                expanded = actionExpanded,
                onExpandedChange = { actionExpanded = !actionExpanded }
            ) {
                OutlinedTextField(
                    value = if (selectedAction == "ignore") stringResource(R.string.settings_rule_ignore) else stringResource(R.string.settings_rule_auto_approve),
                    onValueChange = {},
                    readOnly = true,
                    label = { Text(stringResource(R.string.settings_add_rule_action_label)) },
                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = actionExpanded) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable),
                    shape = MaterialTheme.shapes.medium
                )

                ExposedDropdownMenu(
                    expanded = actionExpanded,
                    onDismissRequest = { actionExpanded = false }
                ) {
                    DropdownMenuItem(
                        text = { Text(stringResource(R.string.settings_rule_ignore)) },
                        onClick = {
                            selectedAction = "ignore"
                            actionExpanded = false
                        },
                        leadingIcon = {
                            Icon(Icons.Filled.Block, contentDescription = null)
                        }
                    )
                    DropdownMenuItem(
                        text = { Text(stringResource(R.string.settings_rule_auto_approve)) },
                        onClick = {
                            selectedAction = "auto_approve"
                            actionExpanded = false
                        },
                        leadingIcon = {
                            Icon(Icons.Filled.CheckCircle, contentDescription = null)
                        }
                    )
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            SelkoButton(
                text = stringResource(R.string.settings_add_rule_button),
                onClick = {
                    val input = ruleInput.trim()
                    if (input.isNotBlank()) {
                        if (input.contains("@")) {
                            onCreateRule(input, null, selectedAction)
                        } else {
                            onCreateRule(null, input, selectedAction)
                        }
                        ruleInput = ""
                    }
                },
                enabled = ruleInput.isNotBlank(),
                modifier = Modifier.fillMaxWidth(),
                icon = Icons.Filled.Add
            )
        }
    }

    // Delete confirmation dialog
    ruleToDelete?.let { rule ->
        val actionText = if (rule.action == "ignore") stringResource(R.string.settings_rule_ignore).lowercase() else stringResource(R.string.settings_rule_auto_approve).lowercase()
        val senderText = rule.senderEmail ?: rule.senderDomain ?: stringResource(R.string.settings_rule_unknown_sender)

        AlertDialog(
            onDismissRequest = { ruleToDelete = null },
            title = { Text(stringResource(R.string.settings_delete_rule_title)) },
            text = {
                Text(stringResource(R.string.settings_delete_rule_message, actionText, senderText))
            },
            confirmButton = {
                SelkoButton(
                    text = stringResource(R.string.settings_delete_rule_confirm),
                    onClick = {
                        onDeleteRule(rule.id)
                        ruleToDelete = null
                    }, role = SelkoActionRole.DestructiveOutline
                )
            },
            dismissButton = {
                SelkoButton(stringResource(R.string.settings_delete_rule_cancel), { ruleToDelete = null }, role = SelkoActionRole.Tertiary)
            }
        )
    }
}
