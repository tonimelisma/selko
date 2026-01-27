package net.melisma.selko

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.navigation.compose.rememberNavController
import net.melisma.selko.ui.navigation.SelkoNavHost
import net.melisma.selko.ui.theme.SelkoTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            SelkoTheme {
                val navController = rememberNavController()
                SelkoNavHost(navController = navController)
            }
        }
    }
}