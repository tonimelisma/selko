package net.melisma.selko

import android.graphics.Bitmap
import android.os.Environment
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.io.FileOutputStream

/**
 * Navigates through all 6 screens and saves PNG screenshots.
 *
 * Run with:
 *   ./gradlew installDebug installDebugAndroidTest
 *   adb shell am instrument -w \
 *     -e class net.melisma.selko.ScreenshotCaptureTest \
 *     net.melisma.selko.test/androidx.test.runner.AndroidJUnitRunner
 *
 * Then pull screenshots:
 *   adb pull /sdcard/Android/data/net.melisma.selko/files/Pictures/ /tmp/android-screenshots/
 */
@RunWith(AndroidJUnit4::class)
class ScreenshotCaptureTest {

    private lateinit var device: UiDevice
    private lateinit var outputDir: File

    companion object {
        private const val PACKAGE = "net.melisma.selko"
        private const val TIMEOUT = 15_000L
        private const val SHORT_TIMEOUT = 10_000L
        private const val SCREENSHOT_USER = "screenshots@selko.local"
        private const val SCREENSHOT_PASS = "screenshotpass123"
    }

    @Before
    fun setup() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        device = UiDevice.getInstance(instrumentation)

        // Output directory — accessible without special permissions
        val context = instrumentation.targetContext
        outputDir = context.getExternalFilesDir(Environment.DIRECTORY_PICTURES)!!
        outputDir.mkdirs()

        // Launch the app
        val intent = context.packageManager.getLaunchIntentForPackage(PACKAGE)
        requireNotNull(intent) { "Could not get launch intent for $PACKAGE" }
        intent.addFlags(android.content.Intent.FLAG_ACTIVITY_CLEAR_TASK)
        context.startActivity(intent)

        // Wait for the app to appear
        device.wait(Until.hasObject(By.pkg(PACKAGE).depth(0)), TIMEOUT)
    }

    @Test
    fun captureAllScreenshots() {
        // 1. Login screen
        device.wait(Until.hasObject(By.text("Sign in")), TIMEOUT)
        Thread.sleep(1000)
        saveScreenshot("android-login")

        // 2. Register screen
        val signUpToggle = device.wait(
            Until.findObject(By.text("Don't have an account? Sign up")), SHORT_TIMEOUT
        )
        signUpToggle.click()
        device.wait(Until.hasObject(By.text("Confirm password")), SHORT_TIMEOUT)
        Thread.sleep(500)
        saveScreenshot("android-register")

        // Go back to login
        val loginToggle = device.wait(
            Until.findObject(By.text("Already have an account? Log in")), SHORT_TIMEOUT
        )
        loginToggle.click()
        device.wait(Until.hasObject(By.text("Sign in")), SHORT_TIMEOUT)
        Thread.sleep(500)

        // 3. Log in with seed user
        // Find the EditText parent of each label — Compose OutlinedTextField renders the
        // label as a child TextView inside an EditText node
        val emailLabel = device.wait(Until.findObject(By.text("Email")), SHORT_TIMEOUT)
        val emailField = emailLabel.parent
        emailField.click()
        Thread.sleep(300)
        emailField.text = SCREENSHOT_USER

        val passwordLabel = device.wait(Until.findObject(By.text("Password")), SHORT_TIMEOUT)
        val passwordField = passwordLabel.parent
        passwordField.click()
        Thread.sleep(300)
        passwordField.text = SCREENSHOT_PASS

        // Dismiss keyboard before tapping Sign in
        device.pressBack()
        Thread.sleep(500)

        // Tap the Sign in button
        val signInButton = device.wait(Until.findObject(By.text("Sign in")), SHORT_TIMEOUT)
        signInButton.click()

        // Wait for the review queue to load (indicates successful login)
        device.wait(Until.hasObject(By.text("Review Queue")), TIMEOUT * 2)
        Thread.sleep(3000)

        // 4. Review queue
        saveScreenshot("android-review-queue")

        // 5. History tab — try by content description (icon), then by text
        var historyTab = device.wait(Until.findObject(By.desc("History")), SHORT_TIMEOUT)
        if (historyTab == null) {
            historyTab = device.wait(Until.findObject(By.text("History")), SHORT_TIMEOUT)
        }
        requireNotNull(historyTab) { "Could not find History tab by desc or text" }
        historyTab.click()
        Thread.sleep(2000)
        saveScreenshot("android-history")

        // 6. Settings tab
        val settingsTab = device.wait(Until.findObject(By.text("Settings")), SHORT_TIMEOUT)
        requireNotNull(settingsTab) { "Could not find Settings tab" }
        settingsTab.click()
        Thread.sleep(1000)
        saveScreenshot("android-settings")

        // 7. Go back to Review tab, then navigate to event detail
        val reviewTab = device.wait(Until.findObject(By.text("Review")), SHORT_TIMEOUT)
        requireNotNull(reviewTab) { "Could not find Review tab" }
        reviewTab.click()
        Thread.sleep(2000)

        val editButton = device.wait(Until.findObject(By.desc("Edit")), SHORT_TIMEOUT)
        if (editButton != null) {
            editButton.click()
            device.wait(Until.hasObject(By.text("Event Details")), SHORT_TIMEOUT)
            Thread.sleep(1000)
        }
        saveScreenshot("android-event-detail")
    }

    private fun saveScreenshot(name: String) {
        val bitmap = InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()
            ?: throw AssertionError("Failed to take screenshot for $name")

        val file = File(outputDir, "$name.png")
        FileOutputStream(file).use { out ->
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)
        }
        bitmap.recycle()
    }
}
