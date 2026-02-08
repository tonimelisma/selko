package net.melisma.selko.ui.components

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.vector.ImageVector
import net.melisma.selko.ui.navigation.History
import net.melisma.selko.ui.navigation.Review
import net.melisma.selko.ui.navigation.Settings

data class BottomNavItem(
    val label: String,
    val icon: ImageVector,
    val route: Any
)

val bottomNavItems = listOf(
    BottomNavItem("Review", Icons.AutoMirrored.Filled.List, Review),
    BottomNavItem("History", Icons.Filled.History, History),
    BottomNavItem("Settings", Icons.Filled.Settings, Settings)
)

@Composable
fun SelkoBottomNavigation(
    currentRoute: String?,
    onNavigate: (Any) -> Unit
) {
    NavigationBar {
        bottomNavItems.forEach { item ->
            val routeName = item.route::class.qualifiedName
            NavigationBarItem(
                icon = { Icon(item.icon, contentDescription = item.label) },
                label = { Text(item.label) },
                selected = currentRoute == routeName,
                onClick = { onNavigate(item.route) }
            )
        }
    }
}
