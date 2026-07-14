package net.melisma.selko.ui.components

import androidx.annotation.StringRes
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import net.melisma.selko.R
import net.melisma.selko.ui.navigation.History
import net.melisma.selko.ui.navigation.Review
import net.melisma.selko.ui.navigation.Settings

data class BottomNavItem(
    @param:StringRes val labelResId: Int,
    val icon: ImageVector,
    val route: Any
)

val bottomNavItems = listOf(
    BottomNavItem(R.string.nav_review, Icons.AutoMirrored.Filled.List, Review),
    BottomNavItem(R.string.nav_history, Icons.Filled.History, History),
    BottomNavItem(R.string.nav_settings, Icons.Filled.Settings, Settings)
)

@Composable
fun SelkoBottomNavigation(
    currentRoute: String?,
    onNavigate: (Any) -> Unit
) {
    NavigationBar(
        containerColor = MaterialTheme.colorScheme.surface,
        tonalElevation = 0.dp
    ) {
        bottomNavItems.forEach { item ->
            val routeName = item.route::class.qualifiedName
            val label = stringResource(item.labelResId)
            NavigationBarItem(
                icon = { Icon(item.icon, contentDescription = label) },
                label = { Text(label) },
                selected = currentRoute == routeName,
                onClick = { onNavigate(item.route) },
                colors = NavigationBarItemDefaults.colors(
                    selectedIconColor = MaterialTheme.colorScheme.primary,
                    selectedTextColor = MaterialTheme.colorScheme.primary,
                    indicatorColor = MaterialTheme.colorScheme.primaryContainer
                )
            )
        }
    }
}
