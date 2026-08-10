package net.melisma.selko.ui.navigation

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.toRoute
import io.github.jan.supabase.auth.status.SessionStatus
import net.melisma.selko.data.repository.AuthRepository
import net.melisma.selko.data.repository.LiveUpdateRepository
import net.melisma.selko.ui.screens.auth.AuthScreen
import net.melisma.selko.ui.screens.review.EventDetailScreen
import org.koin.compose.koinInject

@Composable
fun SelkoNavHost(
    navController: NavHostController,
    authRepository: AuthRepository = koinInject(),
    deepLink: DeepLink? = null,
    onDeepLinkConsumed: () -> Unit = {}
) {
    val sessionStatus by authRepository.sessionStatus.collectAsState(initial = SessionStatus.Initializing)
    // Live invalidation wiring (C6): establish the private Broadcast channel
    // for the signed-in user; tear it down on sign-out.
    val liveUpdateRepository: LiveUpdateRepository = koinInject()

    // Handle session status changes
    LaunchedEffect(sessionStatus) {
        when (val status = sessionStatus) {
            is SessionStatus.Authenticated -> {
                status.session.user?.id?.let { liveUpdateRepository.start(it) }
            }
            is SessionStatus.NotAuthenticated -> {
                liveUpdateRepository.stop()
            }
            else -> { /* loading */ }
        }

        // On the first resolved session, NavHost has not installed its graph yet;
        // its startDestination below already reflects that session. Navigating
        // before graph installation crashes cold launches and screenshot tests.
        if (navController.currentDestination == null) return@LaunchedEffect
        when (sessionStatus) {
            is SessionStatus.Authenticated -> {
                navController.navigate(Home) {
                    popUpTo(0) { inclusive = true }
                }
            }
            is SessionStatus.NotAuthenticated -> {
                navController.navigate(Auth) {
                    popUpTo(0) { inclusive = true }
                }
            }
            else -> {
                // Loading states - do nothing, let the UI show loading
            }
        }
    }

    // Show loading while checking session
    if (sessionStatus is SessionStatus.Initializing) {
        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.Center
        ) {
            CircularProgressIndicator()
        }
        return
    }

    NavHost(
        navController = navController,
        startDestination = if (sessionStatus is SessionStatus.Authenticated) Home else Auth
    ) {
        composable<Auth> {
            AuthScreen(
                onAuthSuccess = {
                    navController.navigate(Home) {
                        popUpTo(Auth) { inclusive = true }
                    }
                }
            )
        }

        composable<Home> {
            MainScaffold(
                parentNavController = navController,
                onLogout = {
                    navController.navigate(Auth) {
                        popUpTo(Home) { inclusive = true }
                    }
                },
                deepLink = deepLink,
                onDeepLinkConsumed = onDeepLinkConsumed
            )
        }

        composable<EventDetail> { backStackEntry ->
            val eventDetail = backStackEntry.toRoute<EventDetail>()
            EventDetailScreen(
                eventId = eventDetail.eventId,
                onNavigateBack = {
                    navController.popBackStack()
                }
            )
        }
    }
}
