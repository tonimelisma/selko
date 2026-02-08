package net.melisma.selko.ui.navigation

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.Composable
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
    onLogout: () -> Unit
) {
    val tabNavController = rememberNavController()
    val navBackStackEntry by tabNavController.currentBackStackEntryAsState()
    val currentRoute = navBackStackEntry?.destination?.route

    Scaffold(
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
