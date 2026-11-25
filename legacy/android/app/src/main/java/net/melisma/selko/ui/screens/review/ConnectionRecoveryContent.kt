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
import net.melisma.selko.data.repository.IntegrationRepository
import net.melisma.selko.data.repository.IntegrationResult
import net.melisma.selko.ui.components.SelkoActionRole
import net.melisma.selko.ui.components.SelkoButton
import net.melisma.selko.ui.theme.SelkoTheme
import org.koin.compose.koinInject
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** One sign-in the connection banner can offer. */
internal enum class RecoverySignIn { GOOGLE, OUTLOOK }

internal enum class RecoveryVerb { RECONNECT, CONNECT_EMAIL, CONNECT_CALENDAR }

internal data class RecoveryAction(val signIn: RecoverySignIn, val verb: RecoveryVerb) {
    /**
     * Gmail stands in for the combined Google consent, which grants Gmail and
     * Google Calendar together (`/integrations/google/auth`).
     */
    val authProvider: IntegrationProvider
        get() = if (signIn == RecoverySignIn.GOOGLE) IntegrationProvider.GMAIL else IntegrationProvider.OUTLOOK

    val labelRes: Int
        get() = when (verb) {
            RecoveryVerb.RECONNECT -> if (signIn == RecoverySignIn.GOOGLE) {
                R.string.recovery_reconnect_google
            } else {
                R.string.recovery_reconnect_outlook
            }
            RecoveryVerb.CONNECT_EMAIL -> if (signIn == RecoverySignIn.GOOGLE) {
                R.string.recovery_connect_gmail
            } else {
                R.string.recovery_connect_outlook
            }
            RecoveryVerb.CONNECT_CALENDAR -> if (signIn == RecoverySignIn.GOOGLE) {
                R.string.recovery_connect_google_calendar
            } else {
                R.string.recovery_connect_outlook_calendar
            }
        }
}

/** What a lapsed sign-in stopped doing. */
internal enum class LostAccess { MAIL, CALENDAR, MAIL_AND_CALENDAR }

internal sealed interface RecoveryKind {
    data class SignedOut(val signIn: RecoverySignIn, val lost: LostAccess) : RecoveryKind
    data object Accounts : RecoveryKind
    data object ConnectEmail : RecoveryKind
    data object ConnectCalendar : RecoveryKind
}

internal data class RecoveryPlan(val kind: RecoveryKind, val actions: List<RecoveryAction>) {
    val titleRes: Int
        get() = when (kind) {
            is RecoveryKind.SignedOut -> if (kind.signIn == RecoverySignIn.GOOGLE) {
                R.string.recovery_google_title
            } else {
                R.string.recovery_outlook_title
            }
            RecoveryKind.Accounts -> R.string.recovery_accounts_title
            RecoveryKind.ConnectEmail -> R.string.recovery_connect_email_title
            RecoveryKind.ConnectCalendar -> R.string.recovery_connect_calendar_title
        }

    val messageRes: Int
        get() = when (kind) {
            is RecoveryKind.SignedOut -> when (kind.signIn) {
                RecoverySignIn.GOOGLE -> when (kind.lost) {
                    LostAccess.MAIL_AND_CALENDAR -> R.string.recovery_google_mail_and_calendar
                    LostAccess.MAIL -> R.string.recovery_google_mail
                    LostAccess.CALENDAR -> R.string.recovery_google_calendar
                }
                RecoverySignIn.OUTLOOK -> when (kind.lost) {
                    LostAccess.MAIL_AND_CALENDAR -> R.string.recovery_outlook_mail_and_calendar
                    LostAccess.MAIL -> R.string.recovery_outlook_mail
                    LostAccess.CALENDAR -> R.string.recovery_outlook_calendar
                }
            }
            RecoveryKind.Accounts -> R.string.recovery_accounts
            RecoveryKind.ConnectEmail -> R.string.recovery_connect_email
            RecoveryKind.ConnectCalendar -> R.string.recovery_connect_calendar
        }
}

private fun lostAccess(mail: Boolean, calendar: Boolean): LostAccess = when {
    mail && calendar -> LostAccess.MAIL_AND_CALENDAR
    mail -> LostAccess.MAIL
    else -> LostAccess.CALENDAR
}

/**
 * What the connection banner asks for, written from the user's side: name the
 * account that stopped working and what it stopped doing, then offer the one
 * sign-in that fixes it. Null when nothing needs the user.
 *
 * A lapsed sign-in comes first, because it is the account the user already
 * chose. Offering a different provider beside it made the banner a menu of
 * equal-looking buttons for a problem with one answer; switching providers
 * stays in Settings.
 */
internal fun recoveryPlanFor(integrations: List<Integration>): RecoveryPlan? {
    val rows = integrations.filter { it.provider != IntegrationProvider.GOOGLE_PHOTOS }
    val gmail = rows.firstOrNull { it.provider == IntegrationProvider.GMAIL }
    val googleCalendar = rows.firstOrNull { it.provider == IntegrationProvider.GOOGLE_CALENDAR }
    val outlook = rows.firstOrNull { it.provider == IntegrationProvider.OUTLOOK }
    val calendarWritable = rows.hasWritableCalendar()

    // A lapsed Google Calendar is not worth a prompt while Outlook Calendar works.
    val googleMailLost = gmail != null && gmail.status != IntegrationStatus.ACTIVE
    val googleCalendarLost = googleCalendar != null &&
        googleCalendar.status != IntegrationStatus.ACTIVE && !calendarWritable
    val outlookLost = outlook != null && outlook.status != IntegrationStatus.ACTIVE

    if ((googleMailLost || googleCalendarLost) && outlookLost) {
        return RecoveryPlan(
            RecoveryKind.Accounts,
            listOf(
                RecoveryAction(RecoverySignIn.GOOGLE, RecoveryVerb.RECONNECT),
                RecoveryAction(RecoverySignIn.OUTLOOK, RecoveryVerb.RECONNECT)
            )
        )
    }
    if (outlookLost) {
        val hadCalendar = outlook!!.scopes.orEmpty().any { it.lowercase().endsWith("calendars.readwrite") }
        return RecoveryPlan(
            RecoveryKind.SignedOut(RecoverySignIn.OUTLOOK, lostAccess(true, hadCalendar && !calendarWritable)),
            listOf(RecoveryAction(RecoverySignIn.OUTLOOK, RecoveryVerb.RECONNECT))
        )
    }
    if (googleMailLost || googleCalendarLost) {
        return RecoveryPlan(
            RecoveryKind.SignedOut(RecoverySignIn.GOOGLE, lostAccess(googleMailLost, googleCalendarLost)),
            listOf(RecoveryAction(RecoverySignIn.GOOGLE, RecoveryVerb.RECONNECT))
        )
    }

    val gmailActive = gmail?.status == IntegrationStatus.ACTIVE
    val outlookActive = outlook?.status == IntegrationStatus.ACTIVE
    if (!gmailActive && !outlookActive) {
        // Two equal choices are right here: Selko cannot know which mail the user has.
        return RecoveryPlan(
            RecoveryKind.ConnectEmail,
            listOf(
                RecoveryAction(RecoverySignIn.GOOGLE, RecoveryVerb.CONNECT_EMAIL),
                RecoveryAction(RecoverySignIn.OUTLOOK, RecoveryVerb.CONNECT_EMAIL)
            )
        )
    }
    if (!calendarWritable) {
        // Offer the calendar of the account the user already signed in with.
        val signIn = if (gmailActive) RecoverySignIn.GOOGLE else RecoverySignIn.OUTLOOK
        return RecoveryPlan(
            RecoveryKind.ConnectCalendar,
            listOf(RecoveryAction(signIn, RecoveryVerb.CONNECT_CALENDAR))
        )
    }
    return null
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

    if (catchUp == null && plan == null) return

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

        plan?.let { plan ->
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
                            Text(text = stringResource(plan.titleRes), style = MaterialTheme.typography.titleMedium)
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = stringResource(plan.messageRes),
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(16.dp))

                    plan.actions.forEachIndexed { index, action ->
                        val provider = action.authProvider
                        SelkoButton(
                            text = stringResource(action.labelRes),
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

                    Spacer(modifier = Modifier.height(8.dp))
                    SelkoButton(
                        text = stringResource(R.string.recovery_manage_connections),
                        onClick = {
                            context.startActivity(
                                Intent(Intent.ACTION_VIEW, Uri.parse("selko://settings"))
                                    .setPackage(context.packageName)
                                    // Reuse the running activity; it routes via onNewIntent.
                                    .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
                            )
                        },
                        modifier = Modifier.fillMaxWidth(),
                        role = SelkoActionRole.Tertiary
                    )
                }
            }
        }
    }
}
