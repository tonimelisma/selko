package net.melisma.selko.ui.screens.review

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.WarningAmber
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import net.melisma.selko.R
import net.melisma.selko.data.model.Integration
import net.melisma.selko.data.model.IntegrationProvider
import net.melisma.selko.data.model.IntegrationRecovery
import net.melisma.selko.data.model.IntegrationRecoveryStatus
import net.melisma.selko.data.model.IntegrationStatus
import net.melisma.selko.data.model.hasWritableCalendar
import net.melisma.selko.data.model.needsOutlookCalendarReconnect
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.data.repository.IntegrationResult
import net.melisma.selko.ui.components.SelkoActionRole
import net.melisma.selko.ui.components.SelkoButton
import net.melisma.selko.ui.theme.SelkoTheme
import org.koin.compose.koinInject
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** One sign-in the reconnect banner can offer. */
internal enum class RecoverySignIn { GOOGLE, OUTLOOK }

internal data class RecoveryAction(val signIn: RecoverySignIn, val isReconnect: Boolean) {
    /**
     * Gmail stands in for the combined Google consent, which grants Gmail and
     * Google Calendar together (`/integrations/google/auth`).
     */
    val authProvider: IntegrationProvider
        get() = if (signIn == RecoverySignIn.GOOGLE) IntegrationProvider.GMAIL else IntegrationProvider.OUTLOOK
}

internal enum class RecoveryTitle { EMAIL, CONNECT_CALENDAR, RECONNECT_CALENDAR, ATTENTION }

internal data class RecoveryPlan(val title: RecoveryTitle, val actions: List<RecoveryAction>)

/**
 * What the reconnect banner offers: one action per sign-in, not per row.
 *
 * Gmail and Google Calendar are separate rows but one Google consent grants
 * both, so offering both only duplicated the same flow. Outlook mail and
 * Outlook Calendar share one row.
 */
internal fun recoveryPlanFor(integrations: List<Integration>): RecoveryPlan {
    val rows = integrations.filter { it.provider != IntegrationProvider.GOOGLE_PHOTOS }
    val googleRows = rows.filter {
        it.provider == IntegrationProvider.GMAIL || it.provider == IntegrationProvider.GOOGLE_CALENDAR
    }
    val outlook = rows.firstOrNull { it.provider == IntegrationProvider.OUTLOOK }
    val emailConnected = rows.any {
        it.provider in setOf(IntegrationProvider.GMAIL, IntegrationProvider.OUTLOOK) &&
            it.status == IntegrationStatus.ACTIVE
    }
    val calendarConnected = rows.hasWritableCalendar()
    val outlookNeedsCalendar = outlook != null && outlook.status == IntegrationStatus.ACTIVE &&
        rows.needsOutlookCalendarReconnect()

    // A lapsed Gmail always matters. A lapsed Google Calendar matters only when
    // no calendar is writable; with Outlook Calendar working it is not a reason
    // to prompt.
    var wantsGoogle = rows.any {
        it.provider == IntegrationProvider.GMAIL && it.status != IntegrationStatus.ACTIVE
    }
    var wantsOutlook = outlook != null && outlook.status != IntegrationStatus.ACTIVE
    if (!emailConnected) {
        wantsGoogle = true
        wantsOutlook = true
    } else if (!calendarConnected) {
        wantsGoogle = true
        if (outlook != null && (outlook.status != IntegrationStatus.ACTIVE || outlookNeedsCalendar)) {
            wantsOutlook = true
        }
    }

    val google = if (wantsGoogle) {
        listOf(RecoveryAction(RecoverySignIn.GOOGLE, isReconnect = googleRows.isNotEmpty()))
    } else {
        emptyList()
    }
    val outlookAction = if (wantsOutlook) {
        listOf(RecoveryAction(RecoverySignIn.OUTLOOK, isReconnect = outlook != null))
    } else {
        emptyList()
    }
    // An Outlook account that only lacks calendar consent is the shortest fix,
    // so it is offered first.
    val outlookFirst = emailConnected && !calendarConnected && outlookNeedsCalendar
    val actions = if (outlookFirst) outlookAction + google else google + outlookAction

    val title = when {
        !emailConnected -> RecoveryTitle.EMAIL
        !calendarConnected -> {
            val hadCalendar = rows.any { it.provider == IntegrationProvider.GOOGLE_CALENDAR } ||
                outlook?.scopes.orEmpty().any { it.lowercase().endsWith("calendars.readwrite") }
            if (hadCalendar) RecoveryTitle.RECONNECT_CALENDAR else RecoveryTitle.CONNECT_CALENDAR
        }
        else -> RecoveryTitle.ATTENTION
    }
    return RecoveryPlan(title, actions)
}

internal data class CatchUpDisplay(
    val icon: ImageVector,
    val tint: Color,
    val title: String,
    val description: String
)

@Composable
internal fun rememberCatchUpDisplay(
    recovery: IntegrationRecovery?,
    justCaughtUp: Boolean
): CatchUpDisplay? {
    if (recovery == null) return null
    return when (recovery.status) {
        IntegrationRecoveryStatus.PENDING,
        IntegrationRecoveryStatus.PROCESSING -> CatchUpDisplay(
            icon = Icons.Filled.Sync,
            tint = SelkoTheme.colors.warning,
            title = stringResource(R.string.recovery_catch_up_starting_title),
            description = stringResource(R.string.recovery_catch_up_starting_description)
        )
        IntegrationRecoveryStatus.WAITING -> CatchUpDisplay(
            icon = Icons.Filled.Sync,
            tint = SelkoTheme.colors.warning,
            title = stringResource(R.string.recovery_catch_up_remaining_title, recovery.remainingCount ?: 0),
            description = stringResource(R.string.recovery_catch_up_remaining_description)
        )
        IntegrationRecoveryStatus.COMPLETED -> if (justCaughtUp) {
            CatchUpDisplay(
                icon = Icons.Filled.CheckCircle,
                tint = SelkoTheme.colors.success,
                title = stringResource(R.string.recovery_catch_up_completed_title),
                description = stringResource(R.string.recovery_catch_up_completed_description)
            )
        } else {
            null
        }
        IntegrationRecoveryStatus.COMPLETED_WITH_ERRORS -> CatchUpDisplay(
            icon = Icons.Filled.WarningAmber,
            tint = SelkoTheme.colors.warning,
            title = stringResource(R.string.recovery_catch_up_errors_title, recovery.needingAttentionCount),
            description = stringResource(R.string.recovery_catch_up_errors_description, recovery.needingAttentionCount)
        )
        IntegrationRecoveryStatus.FAILED -> CatchUpDisplay(
            icon = Icons.Filled.WarningAmber,
            tint = MaterialTheme.colorScheme.error,
            title = stringResource(R.string.recovery_catch_up_failed_title),
            description = stringResource(R.string.recovery_catch_up_failed_description)
        )
        IntegrationRecoveryStatus.SUPERSEDED -> null
    }
}

@Composable
fun ConnectionRecoveryContent(
    integrations: List<Integration>,
    onAuthorize: suspend (IntegrationProvider) -> Result<String>,
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val integrationRepository = koinInject<IntegrationRepository>()
    var connectingProvider by remember { mutableStateOf<IntegrationProvider?>(null) }
    var connectError by remember { mutableStateOf<String?>(null) }
    var recovery by remember { mutableStateOf<IntegrationRecovery?>(null) }
    var justCaughtUp by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        while (true) {
            val previous = recovery
            when (val result = integrationRepository.fetchCalendarRecovery()) {
                is IntegrationResult.Success -> {
                    recovery = result.data
                    if (previous != null &&
                        previous.status != IntegrationRecoveryStatus.COMPLETED &&
                        recovery?.status == IntegrationRecoveryStatus.COMPLETED
                    ) {
                        justCaughtUp = true
                        delay(4000)
                        justCaughtUp = false
                    }
                }
                is IntegrationResult.Error -> {
                    // Keep the reconnect card authoritative on transient failures.
                }
            }
            if (recovery?.isActive == true) {
                delay(5000)
            } else {
                break
            }
        }
    }

    val plan = recoveryPlanFor(integrations)
    val catchUp = rememberCatchUpDisplay(recovery, justCaughtUp)

    if (catchUp == null && plan.actions.isEmpty()) return

    val title = when (plan.title) {
        RecoveryTitle.EMAIL -> stringResource(R.string.recovery_email_title)
        RecoveryTitle.CONNECT_CALENDAR -> stringResource(R.string.recovery_any_calendar_title)
        RecoveryTitle.RECONNECT_CALENDAR -> stringResource(R.string.recovery_calendar_title)
        RecoveryTitle.ATTENTION -> stringResource(R.string.recovery_attention_title)
    }
    val description = when (plan.title) {
        RecoveryTitle.EMAIL -> stringResource(R.string.recovery_email_description)
        RecoveryTitle.CONNECT_CALENDAR,
        RecoveryTitle.RECONNECT_CALENDAR -> stringResource(R.string.recovery_calendar_description)
        RecoveryTitle.ATTENTION -> stringResource(R.string.recovery_attention_description)
    }

    Column(modifier = modifier.fillMaxWidth()) {
        catchUp?.let {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surface
                ),
                border = BorderStroke(1.dp, it.tint),
                shape = MaterialTheme.shapes.large
            ) {
                Row(
                    modifier = Modifier.padding(16.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalAlignment = Alignment.Top
                ) {
                    Icon(
                        imageVector = it.icon,
                        contentDescription = null,
                        tint = it.tint
                    )
                    Column {
                        Text(text = it.title, style = MaterialTheme.typography.titleMedium)
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = it.description,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }
        }

        if (plan.actions.isNotEmpty()) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surface
                ),
                border = BorderStroke(1.dp, SelkoTheme.colors.warning),
                shape = MaterialTheme.shapes.large
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    connectError?.let { message ->
                        Text(
                            text = message,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.error
                        )
                        Spacer(modifier = Modifier.height(12.dp))
                    }

                    Row(
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                        verticalAlignment = Alignment.Top
                    ) {
                        Icon(
                            imageVector = Icons.Filled.WarningAmber,
                            contentDescription = null,
                            tint = SelkoTheme.colors.warning
                        )
                        Column {
                            Text(text = title, style = MaterialTheme.typography.titleMedium)
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = description,
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(16.dp))

                    plan.actions.forEachIndexed { index, action ->
                        val provider = action.authProvider
                        val providerName = when (action.signIn) {
                            RecoverySignIn.GOOGLE -> stringResource(R.string.recovery_google)
                            RecoverySignIn.OUTLOOK -> stringResource(R.string.settings_outlook)
                        }
                        val label = if (action.isReconnect) {
                            stringResource(R.string.recovery_reconnect_provider, providerName)
                        } else {
                            stringResource(R.string.recovery_connect_provider, providerName)
                        }
                        SelkoButton(
                            text = label,
                            onClick = {
                                scope.launch {
                                    connectingProvider = provider
                                    connectError = null
                                    onAuthorize(provider)
                                        .onSuccess { url ->
                                            try {
                                                context.startActivity(
                                                    Intent(Intent.ACTION_VIEW, Uri.parse(url))
                                                )
                                            } catch (_: android.content.ActivityNotFoundException) {
                                                connectError = context.getString(
                                                    R.string.recovery_connect_failed
                                                )
                                            }
                                        }
                                        .onFailure { error ->
                                            connectError = error.message
                                                ?: context.getString(R.string.recovery_connect_failed)
                                        }
                                    connectingProvider = null
                                }
                            },
                            modifier = Modifier.fillMaxWidth(),
                            role = if (index == 0) SelkoActionRole.Primary else SelkoActionRole.Secondary,
                            enabled = connectingProvider == null,
                            loading = connectingProvider == provider
                        )
                        if (index != plan.actions.lastIndex) {
                            Spacer(modifier = Modifier.height(8.dp))
                        }
                    }

                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = stringResource(R.string.recovery_settings_note),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }
}
