package net.melisma.selko.ui.screens.settings

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.BorderStroke
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
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Block
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Logout
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Snackbar
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import org.koin.androidx.compose.koinViewModel

@Composable
fun SettingsScreen(
    onLogout: () -> Unit,
    viewModel: SettingsViewModel = koinViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()

    Box(modifier = Modifier.fillMaxSize()) {
        if (uiState.isLoading) {
            CircularProgressIndicator(
                modifier = Modifier.align(Alignment.Center)
            )
        } else {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp)
            ) {
                Text(
                    text = stringResource(R.string.settings_title),
                    style = MaterialTheme.typography.headlineSmall
                )

                Spacer(modifier = Modifier.height(24.dp))

                // Connected Accounts Section
                SectionHeader(title = stringResource(R.string.settings_section_connected_accounts))
                Spacer(modifier = Modifier.height(8.dp))
                ConnectedAccountsSection(
                    uiState = uiState,
                    onDisconnect = { viewModel.disconnectIntegration(it) },
                    gmailAuthUrl = viewModel.getGmailAuthUrl(),
                    outlookAuthUrl = viewModel.getOutlookAuthUrl(),
                    calendarAuthUrl = viewModel.getCalendarAuthUrl(),
                    photosAuthUrl = viewModel.getPhotosAuthUrl()
                )

                Spacer(modifier = Modifier.height(24.dp))

                // Calendar Defaults Section
                SectionHeader(title = stringResource(R.string.settings_section_calendar_defaults))
                Spacer(modifier = Modifier.height(8.dp))
                CalendarDefaultsSection(
                    uiState = uiState,
                    onCalendarSelected = { viewModel.onCalendarSelected(it) },
                    onDefaultInviteesChange = { viewModel.onDefaultInviteesChange(it) },
                    onSaveInvitees = { viewModel.saveCalendarSettings() }
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
                        Text(stringResource(R.string.settings_dismiss))
                    }
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
        text = title,
        style = MaterialTheme.typography.titleMedium,
        color = MaterialTheme.colorScheme.primary
    )
}

@Composable
private fun ConnectedAccountsSection(
    uiState: SettingsUiState,
    onDisconnect: (IntegrationProvider) -> Unit,
    gmailAuthUrl: String,
    outlookAuthUrl: String,
    calendarAuthUrl: String,
    photosAuthUrl: String
) {
    val context = LocalContext.current
    val gmailIntegration = uiState.integrations.find { it.provider == IntegrationProvider.GMAIL }
    val outlookIntegration = uiState.integrations.find { it.provider == IntegrationProvider.OUTLOOK }
    val calendarIntegration = uiState.integrations.find { it.provider == IntegrationProvider.GOOGLE_CALENDAR }
    val photosIntegration = uiState.integrations.find { it.provider == IntegrationProvider.GOOGLE_PHOTOS }

    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
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

            HorizontalDivider(modifier = Modifier.padding(vertical = 8.dp))

            // Google Photos
            IntegrationRow(
                icon = Icons.Filled.PhotoCamera,
                label = stringResource(R.string.settings_google_photos),
                email = photosIntegration?.providerEmail,
                isConnected = photosIntegration?.status == IntegrationStatus.ACTIVE,
                isDisconnecting = uiState.isDisconnecting,
                onConnect = {
                    try {
                        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(photosAuthUrl))
                        context.startActivity(intent)
                    } catch (_: android.content.ActivityNotFoundException) {
                        // No browser available
                    }
                },
                onDisconnect = { onDisconnect(IntegrationProvider.GOOGLE_PHOTOS) }
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
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = Icons.Filled.CheckCircle,
                    contentDescription = stringResource(R.string.settings_connected),
                    modifier = Modifier.size(16.dp),
                    tint = MaterialTheme.colorScheme.primary
                )
                Spacer(modifier = Modifier.width(8.dp))
                OutlinedButton(
                    onClick = onDisconnect,
                    enabled = !isDisconnecting,
                    colors = ButtonDefaults.outlinedButtonColors(
                        contentColor = MaterialTheme.colorScheme.error
                    ),
                    border = BorderStroke(1.dp, MaterialTheme.colorScheme.error),
                    shape = MaterialTheme.shapes.medium
                ) {
                    if (isDisconnecting) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.error
                        )
                    } else {
                        Text(stringResource(R.string.settings_disconnect))
                    }
                }
            }
        } else {
            OutlinedButton(
                onClick = onConnect,
                shape = MaterialTheme.shapes.medium
            ) {
                Text(stringResource(R.string.settings_connect))
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CalendarDefaultsSection(
    uiState: SettingsUiState,
    onCalendarSelected: (String) -> Unit,
    onDefaultInviteesChange: (String) -> Unit,
    onSaveInvitees: () -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
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
                            .menuAnchor(MenuAnchorType.PrimaryNotEditable),
                        shape = MaterialTheme.shapes.small
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
            }

            // Default invitees
            OutlinedTextField(
                value = uiState.defaultInvitees,
                onValueChange = onDefaultInviteesChange,
                label = { Text(stringResource(R.string.settings_default_invitees)) },
                placeholder = { Text(stringResource(R.string.settings_default_invitees_placeholder)) },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                shape = MaterialTheme.shapes.small
            )

            if (uiState.defaultInvitees.isNotBlank()) {
                Spacer(modifier = Modifier.height(8.dp))
                TextButton(
                    onClick = onSaveInvitees,
                    enabled = !uiState.isSavingCalendarSettings,
                    shape = MaterialTheme.shapes.medium
                ) {
                    if (uiState.isSavingCalendarSettings) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp
                        )
                    } else {
                        Text(stringResource(R.string.settings_save))
                    }
                }
            }
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
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
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
            OutlinedButton(
                onClick = onSignOut,
                modifier = Modifier.fillMaxWidth(),
                enabled = !uiState.isSigningOut,
                colors = ButtonDefaults.outlinedButtonColors(
                    contentColor = MaterialTheme.colorScheme.error
                ),
                border = BorderStroke(1.dp, MaterialTheme.colorScheme.error),
                shape = MaterialTheme.shapes.medium
            ) {
                if (uiState.isSigningOut) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(18.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.error
                    )
                } else {
                    Icon(
                        imageVector = Icons.Filled.Logout,
                        contentDescription = stringResource(R.string.settings_log_out_description),
                        modifier = Modifier.size(18.dp)
                    )
                }
                Spacer(modifier = Modifier.width(8.dp))
                Text(stringResource(R.string.settings_log_out))
            }
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
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
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
                rules.forEachIndexed { index, rule ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 4.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(
                            imageVector = if (rule.action == "ignore") Icons.Filled.Block else Icons.Filled.CheckCircle,
                            contentDescription = null,
                            modifier = Modifier.size(20.dp),
                            tint = if (rule.action == "ignore")
                                MaterialTheme.colorScheme.error
                            else
                                MaterialTheme.colorScheme.primary
                        )
                        Spacer(modifier = Modifier.width(12.dp))
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = if (rule.action == "ignore") stringResource(R.string.settings_rule_ignore) else stringResource(R.string.settings_rule_auto_approve),
                                style = MaterialTheme.typography.bodyMedium
                            )
                            Text(
                                text = rule.senderEmail ?: rule.senderDomain ?: stringResource(R.string.settings_rule_unknown_sender),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        IconButton(onClick = { ruleToDelete = rule }) {
                            Icon(
                                imageVector = Icons.Filled.Delete,
                                contentDescription = stringResource(R.string.settings_rule_delete_description),
                                tint = MaterialTheme.colorScheme.error
                            )
                        }
                    }
                    if (index < rules.lastIndex) {
                        HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))
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
                shape = MaterialTheme.shapes.small
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
                        .menuAnchor(MenuAnchorType.PrimaryNotEditable),
                    shape = MaterialTheme.shapes.small
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

            Button(
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
                shape = MaterialTheme.shapes.medium
            ) {
                Icon(
                    imageVector = Icons.Filled.Add,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp)
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(stringResource(R.string.settings_add_rule_button))
            }
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
                TextButton(
                    onClick = {
                        onDeleteRule(rule.id)
                        ruleToDelete = null
                    },
                    shape = MaterialTheme.shapes.medium
                ) {
                    Text(stringResource(R.string.settings_delete_rule_confirm), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(
                    onClick = { ruleToDelete = null },
                    shape = MaterialTheme.shapes.medium
                ) {
                    Text(stringResource(R.string.settings_delete_rule_cancel))
                }
            }
        )
    }
}
