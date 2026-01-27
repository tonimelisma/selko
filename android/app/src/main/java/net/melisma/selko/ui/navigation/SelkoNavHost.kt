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
import io.github.jan.supabase.auth.status.SessionStatus
import net.melisma.selko.data.repository.AuthRepository
import net.melisma.selko.ui.screens.auth.AuthScreen
import net.melisma.selko.ui.screens.home.HomeScreen
import org.koin.compose.koinInject

@Composable
fun SelkoNavHost(
    navController: NavHostController,
    authRepository: AuthRepository = koinInject()
) {
    val sessionStatus by authRepository.sessionStatus.collectAsState(initial = SessionStatus.Initializing)

    // Handle session status changes
    LaunchedEffect(sessionStatus) {
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
            HomeScreen(
                onLogout = {
                    navController.navigate(Auth) {
                        popUpTo(Home) { inclusive = true }
                    }
                }
            )
        }
    }
}
