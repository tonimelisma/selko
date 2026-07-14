package net.melisma.selko.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import net.melisma.selko.R

val FigtreeFontFamily = FontFamily(
    Font(R.font.figtree_regular, FontWeight.Normal),
    Font(R.font.figtree_medium, FontWeight.Medium),
    Font(R.font.figtree_semibold, FontWeight.SemiBold),
    Font(R.font.figtree_bold, FontWeight.Bold),
    Font(R.font.figtree_extrabold, FontWeight.ExtraBold)
)

val Typography = Typography(
    displayLarge = TextStyle(fontFamily = FigtreeFontFamily, fontWeight = FontWeight.ExtraBold, fontSize = 36.sp, lineHeight = 43.sp, letterSpacing = (-0.72).sp),
    headlineLarge = TextStyle(fontFamily = FigtreeFontFamily, fontWeight = FontWeight.Bold, fontSize = 28.sp, lineHeight = 36.sp, letterSpacing = (-0.42).sp),
    headlineMedium = TextStyle(fontFamily = FigtreeFontFamily, fontWeight = FontWeight.Bold, fontSize = 22.sp, lineHeight = 30.sp, letterSpacing = (-0.22).sp),
    headlineSmall = TextStyle(fontFamily = FigtreeFontFamily, fontWeight = FontWeight.SemiBold, fontSize = 18.sp, lineHeight = 25.sp, letterSpacing = (-0.09).sp),
    bodyLarge = TextStyle(fontFamily = FigtreeFontFamily, fontWeight = FontWeight.Normal, fontSize = 15.sp, lineHeight = 23.sp, letterSpacing = 0.sp),
    bodyMedium = TextStyle(fontFamily = FigtreeFontFamily, fontWeight = FontWeight.Normal, fontSize = 13.sp, lineHeight = 20.sp, letterSpacing = 0.07.sp),
    bodySmall = TextStyle(fontFamily = FigtreeFontFamily, fontWeight = FontWeight.Normal, fontSize = 11.sp, lineHeight = 16.sp, letterSpacing = 0.22.sp),
    titleLarge = TextStyle(fontFamily = FigtreeFontFamily, fontWeight = FontWeight.Bold, fontSize = 22.sp, lineHeight = 28.sp, letterSpacing = 0.sp),
    titleMedium = TextStyle(fontFamily = FigtreeFontFamily, fontWeight = FontWeight.SemiBold, fontSize = 16.sp, lineHeight = 24.sp, letterSpacing = 0.15.sp),
    titleSmall = TextStyle(fontFamily = FigtreeFontFamily, fontWeight = FontWeight.Medium, fontSize = 14.sp, lineHeight = 20.sp, letterSpacing = 0.1.sp),
    labelLarge = TextStyle(fontFamily = FigtreeFontFamily, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, lineHeight = 20.sp, letterSpacing = 0.1.sp),
    labelMedium = TextStyle(fontFamily = FigtreeFontFamily, fontWeight = FontWeight.Medium, fontSize = 12.sp, lineHeight = 16.sp, letterSpacing = 0.5.sp),
    labelSmall = TextStyle(fontFamily = FigtreeFontFamily, fontWeight = FontWeight.Medium, fontSize = 11.sp, lineHeight = 16.sp, letterSpacing = 0.5.sp)
)
