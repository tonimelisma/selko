package net.melisma.selko.ui.screens.review

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.background
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Email
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import net.melisma.selko.R
import net.melisma.selko.data.model.IntegrationProvider
import net.melisma.selko.ui.components.SelkoLogoMark
import net.melisma.selko.ui.components.SelkoButton
import kotlinx.coroutines.launch

@Composable
fun IntegrationSetupContent(
    isGmailConnected: Boolean,
    isCalendarConnected: Boolean,
    onAuthorize: suspend (IntegrationProvider) -> Result<String>
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var isConnecting by remember { mutableStateOf(false) }
    var connectError by remember { mutableStateOf<String?>(null) }

    fun authorize(provider: IntegrationProvider) {
        if (isConnecting) return
        scope.launch {
            isConnecting = true
            connectError = null
            onAuthorize(provider)
                .onSuccess { url ->
                    try {
                        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                    } catch (_: android.content.ActivityNotFoundException) {
                        connectError = context.getString(R.string.recovery_connect_failed)
                    }
                }
                .onFailure { error ->
                    connectError = error.message
                        ?: context.getString(R.string.recovery_connect_failed)
                }
            isConnecting = false
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        SelkoLogoMark(modifier = Modifier.size(56.dp))

        Spacer(modifier = Modifier.height(24.dp))

        Text(
            text = stringResource(R.string.integration_welcome_title),
            style = MaterialTheme.typography.headlineMedium,
            textAlign = TextAlign.Center
        )

        Spacer(modifier = Modifier.height(12.dp))

        Text(
            text = stringResource(R.string.integration_welcome_subtitle),
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center
        )

        Spacer(modifier = Modifier.height(32.dp))

        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
            border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
            shape = MaterialTheme.shapes.large
        ) {
            Column(modifier = Modifier.padding(20.dp)) {
                connectError?.let { message ->
                    Text(
                        text = message,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.error,
                        textAlign = TextAlign.Center
                    )
                    Spacer(modifier = Modifier.height(12.dp))
                }

                if (!isGmailConnected) {
                    SelkoButton(
                        text = stringResource(R.string.integration_connect_google),
                        onClick = { authorize(IntegrationProvider.GMAIL) },
                        modifier = Modifier.fillMaxWidth(),
                        enabled = !isConnecting,
                        loading = isConnecting
                    )

                    Spacer(modifier = Modifier.height(8.dp))

                    Text(
                        text = stringResource(R.string.integration_connect_google_note),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center
                    )
                } else if (!isCalendarConnected) {
                    Text(
                        text = stringResource(R.string.integration_gmail_connected_note),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center
                    )

                    Spacer(modifier = Modifier.height(16.dp))

                    SelkoButton(
                        text = stringResource(R.string.integration_connect_calendar),
                        onClick = { authorize(IntegrationProvider.GOOGLE_CALENDAR) },
                        modifier = Modifier.fillMaxWidth(),
                        enabled = !isConnecting,
                        loading = isConnecting
                    )
                }
            }
        }
    }
}
