package net.melisma.selko.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import net.melisma.selko.data.repository.AuthRepository
import net.melisma.selko.ui.screens.auth.AuthScreen
import net.melisma.selko.ui.screens.home.HomeScreen
import org.koin.compose.koinInject

@Composable
fun SelkoNavHost(
    navController: NavHostController,
    authRepository: AuthRepository = koinInject()
) {
    val isLoggedIn by authRepository.isLoggedIn.collectAsState(initial = false)

    LaunchedEffect(isLoggedIn) {
        if (isLoggedIn) {
            navController.navigate(Home) {
                popUpTo(Auth) { inclusive = true }
            }
        } else {
            navController.navigate(Auth) {
                popUpTo(Home) { inclusive = true }
            }
        }
    }

    NavHost(
        navController = navController,
        startDestination = Auth
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
