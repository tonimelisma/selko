package net.melisma.selko

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.navigation.compose.rememberNavController
import net.melisma.selko.ui.navigation.DeepLink
import net.melisma.selko.ui.navigation.SelkoNavHost
import net.melisma.selko.ui.navigation.parseDeepLink
import net.melisma.selko.ui.theme.SelkoTheme

class MainActivity : ComponentActivity() {
    private var pendingDeepLink by mutableStateOf<DeepLink?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        pendingDeepLink = parseDeepLink(intent?.data)

        setContent {
            SelkoTheme {
                val navController = rememberNavController()
                SelkoNavHost(
                    navController = navController,
                    deepLink = pendingDeepLink,
                    onDeepLinkConsumed = { pendingDeepLink = null }
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        pendingDeepLink = parseDeepLink(intent.data)
    }
}
