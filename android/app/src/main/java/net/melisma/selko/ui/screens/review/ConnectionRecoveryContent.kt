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
import androidx.compose.material.icons.filled.WarningAmber
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import net.melisma.selko.R
import net.melisma.selko.data.model.Integration
import net.melisma.selko.data.model.IntegrationProvider
import net.melisma.selko.data.model.IntegrationStatus
import net.melisma.selko.ui.components.SelkoActionRole
import net.melisma.selko.ui.components.SelkoButton
import net.melisma.selko.ui.theme.SelkoTheme
import kotlinx.coroutines.launch

internal fun recoveryProvidersFor(
    integrations: List<Integration>
): List<IntegrationProvider> {
    val emailConnected = integrations.any {
        it.provider in setOf(IntegrationProvider.GMAIL, IntegrationProvider.OUTLOOK) &&
            it.status == IntegrationStatus.ACTIVE
    }
    val calendarConnected = integrations.any {
        it.provider == IntegrationProvider.GOOGLE_CALENDAR &&
            it.status == IntegrationStatus.ACTIVE
    }
    return when {
        !emailConnected -> buildList {
            add(IntegrationProvider.GMAIL)
            add(IntegrationProvider.OUTLOOK)
            if (!calendarConnected) add(IntegrationProvider.GOOGLE_CALENDAR)
        }
        !calendarConnected -> buildList {
            add(IntegrationProvider.GOOGLE_CALENDAR)
            integrations
                .filter {
                    it.provider in setOf(IntegrationProvider.GMAIL, IntegrationProvider.OUTLOOK) &&
                        it.status != IntegrationStatus.ACTIVE
                }
                .mapTo(this) { it.provider }
        }
        else -> integrations
            .filter {
                it.provider != IntegrationProvider.GOOGLE_PHOTOS &&
                    it.status != IntegrationStatus.ACTIVE
            }
            .map { it.provider }
    }.distinct()
}

@Composable
fun ConnectionRecoveryContent(
    integrations: List<Integration>,
    onAuthorize: suspend (IntegrationProvider) -> Result<String>,
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var connectingProvider by remember { mutableStateOf<IntegrationProvider?>(null) }
    var connectError by remember { mutableStateOf<String?>(null) }
    val emailConnected = integrations.any {
        it.provider in setOf(IntegrationProvider.GMAIL, IntegrationProvider.OUTLOOK) &&
            it.status == IntegrationStatus.ACTIVE
    }
    val calendarConnected = integrations.any {
        it.provider == IntegrationProvider.GOOGLE_CALENDAR &&
            it.status == IntegrationStatus.ACTIVE
    }
    val recoveryProviders = recoveryProvidersFor(integrations)

    if (recoveryProviders.isEmpty()) return

    val title = when {
        !emailConnected -> stringResource(R.string.recovery_email_title)
        !calendarConnected -> stringResource(R.string.recovery_calendar_title)
        else -> stringResource(R.string.recovery_attention_title)
    }
    val description = when {
        !emailConnected -> stringResource(R.string.recovery_email_description)
        !calendarConnected -> stringResource(R.string.recovery_calendar_description)
        else -> stringResource(R.string.recovery_attention_description)
    }

    Card(
        modifier = modifier.fillMaxWidth(),
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

            recoveryProviders.forEachIndexed { index, provider ->
                val integration = integrations.find { it.provider == provider }
                val reconnecting = integration != null &&
                    integration.status != IntegrationStatus.ACTIVE
                val providerName = when (provider) {
                    IntegrationProvider.GMAIL -> stringResource(R.string.settings_gmail)
                    IntegrationProvider.OUTLOOK -> stringResource(R.string.settings_outlook)
                    IntegrationProvider.GOOGLE_CALENDAR ->
                        stringResource(R.string.settings_google_calendar)
                    IntegrationProvider.GOOGLE_PHOTOS -> return@forEachIndexed
                }
                val label = if (reconnecting) {
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
                if (index != recoveryProviders.lastIndex) {
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
