package net.melisma.selko.ui.navigation

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import net.melisma.selko.ui.components.SelkoBottomNavigation
import net.melisma.selko.ui.screens.history.HistoryScreen
import net.melisma.selko.ui.screens.review.ReviewQueueScreen
import net.melisma.selko.ui.screens.settings.SettingsScreen

@Composable
fun MainScaffold(
    parentNavController: NavHostController,
    onLogout: () -> Unit,
    deepLink: DeepLink? = null,
    onDeepLinkConsumed: () -> Unit = {}
) {
    val tabNavController = rememberNavController()
    val navBackStackEntry by tabNavController.currentBackStackEntryAsState()
    val currentRoute = navBackStackEntry?.destination?.route

    // Handle deep link tab navigation
    LaunchedEffect(deepLink) {
        when (deepLink) {
            is DeepLink.ReviewTab -> {
                tabNavController.navigate(Review) {
                    popUpTo(tabNavController.graph.startDestinationId) {
                        saveState = true
                    }
                    launchSingleTop = true
                    restoreState = true
                }
                onDeepLinkConsumed()
            }
            is DeepLink.HistoryTab -> {
                tabNavController.navigate(History) {
                    popUpTo(tabNavController.graph.startDestinationId) {
                        saveState = true
                    }
                    launchSingleTop = true
                    restoreState = true
                }
                onDeepLinkConsumed()
            }
            is DeepLink.SettingsTab -> {
                tabNavController.navigate(Settings) {
                    popUpTo(tabNavController.graph.startDestinationId) {
                        saveState = true
                    }
                    launchSingleTop = true
                    restoreState = true
                }
                onDeepLinkConsumed()
            }
            is DeepLink.EventDetail -> {
                parentNavController.navigate(
                    net.melisma.selko.ui.navigation.EventDetail(deepLink.eventId)
                ) {
                    launchSingleTop = true
                }
                onDeepLinkConsumed()
            }
            null -> { /* No deep link to handle */ }
        }
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        bottomBar = {
            SelkoBottomNavigation(
                currentRoute = currentRoute,
                onNavigate = { route ->
                    tabNavController.navigate(route) {
                        popUpTo(tabNavController.graph.startDestinationId) {
                            saveState = true
                        }
                        launchSingleTop = true
                        restoreState = true
                    }
                }
            )
        }
    ) { paddingValues ->
        NavHost(
            navController = tabNavController,
            startDestination = Review,
            modifier = Modifier.padding(paddingValues)
        ) {
            composable<Review> {
                ReviewQueueScreen(
                    onNavigateToEventDetail = { eventId ->
                        parentNavController.navigate(EventDetail(eventId))
                    }
                )
            }

            composable<History> {
                HistoryScreen()
            }

            composable<Settings> {
                SettingsScreen(
                    onLogout = onLogout
                )
            }
        }
    }
}
