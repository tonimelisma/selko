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

        // Dismiss any "System UI isn't responding" dialogs from cold boot
        dismissSystemDialogs()
    }

    @Test
    fun captureAllScreenshots() {
        // 1. Login screen
        device.wait(Until.hasObject(By.text("Sign in")), TIMEOUT)
        dismissSystemDialogs()
        Thread.sleep(1000)
        saveScreenshot("android-login")

        // 2. Register screen
        val signUpToggle = device.wait(
            Until.findObject(By.text("Don't have an account? Sign up")), SHORT_TIMEOUT
        )
        requireNotNull(signUpToggle) { "Could not find 'Sign up' toggle on login screen" }
        signUpToggle.click()
        device.wait(Until.hasObject(By.text("Confirm password")), SHORT_TIMEOUT)
        Thread.sleep(500)
        saveScreenshot("android-register")

        // Go back to login
        val loginToggle = device.wait(
            Until.findObject(By.text("Already have an account? Log in")), SHORT_TIMEOUT
        )
        requireNotNull(loginToggle) { "Could not find 'Log in' toggle on register screen" }
        loginToggle.click()
        device.wait(Until.hasObject(By.text("Sign in")), SHORT_TIMEOUT)
        Thread.sleep(500)

        // 3. Log in with seed user (retry up to 3 times — cold-booted emulator networking
        //    may not be ready, causing Supabase auth timeouts)
        var loggedIn = false
        for (attempt in 1..3) {
            val emailLabel = device.wait(Until.findObject(By.text("Email")), SHORT_TIMEOUT)
            requireNotNull(emailLabel) { "Could not find Email field on login screen (attempt $attempt)" }
            val emailField = emailLabel.parent
            emailField.click()
            Thread.sleep(300)
            emailField.text = SCREENSHOT_USER

            val passwordLabel = device.wait(Until.findObject(By.text("Password")), SHORT_TIMEOUT)
            requireNotNull(passwordLabel) { "Could not find Password field on login screen (attempt $attempt)" }
            val passwordField = passwordLabel.parent
            passwordField.click()
            Thread.sleep(300)
            passwordField.text = SCREENSHOT_PASS

            // Try to find Sign in button; dismiss keyboard first if it's blocking
            Thread.sleep(500)
            var signInButton = device.findObject(By.text("Sign in"))
            if (signInButton == null) {
                // Keyboard may be covering the button — dismiss it
                device.pressBack()
                Thread.sleep(500)
                signInButton = device.wait(Until.findObject(By.text("Sign in")), SHORT_TIMEOUT)
            }
            requireNotNull(signInButton) { "Could not find Sign in button (attempt $attempt)" }
            signInButton.click()

            // Wait for the review queue to load
            loggedIn = device.wait(Until.hasObject(By.text("Review Queue")), TIMEOUT * 2)
            if (loggedIn) break

            // Login failed (likely network timeout) — wait and retry
            Thread.sleep(3000)
        }
        require(loggedIn) { "Failed to log in after 3 attempts — check emulator networking and Supabase" }
        Thread.sleep(3000)

        // 4. Review queue
        saveScreenshot("android-review-queue")

        // 5. History tab
        clickTab("History")
        Thread.sleep(2000)
        saveScreenshot("android-history")

        // 6. Settings tab
        clickTab("Settings")
        Thread.sleep(2000)
        saveScreenshot("android-settings")

        // 7. Go back to Review tab, then navigate to event detail
        clickTab("Review")
        Thread.sleep(2000)

        val editButton = device.wait(Until.findObject(By.text("Edit")), SHORT_TIMEOUT)
        if (editButton != null) {
            editButton.click()
            device.wait(Until.hasObject(By.text("Event Details")), SHORT_TIMEOUT)
            Thread.sleep(1000)
        }
        saveScreenshot("android-event-detail")
    }

    private fun clickTab(label: String) {
        // Use By.text() to find the label Text composable.  Clicking the Text child
        // of a Compose NavigationBarItem propagates the click to the item's onClick.
        // (By.desc() finds the Icon child, whose click does NOT propagate.)
        val tab = device.wait(Until.findObject(By.text(label)), SHORT_TIMEOUT)
        requireNotNull(tab) { "Could not find '$label' tab" }
        tab.click()
    }

    private fun dismissSystemDialogs() {
        // Repeatedly dismiss "System UI isn't responding" and similar dialogs
        repeat(3) {
            val waitButton = device.findObject(By.text("Wait"))
            if (waitButton != null) {
                waitButton.click()
                Thread.sleep(1000)
            }
            val closeButton = device.findObject(By.text("Close app"))
            if (closeButton != null) {
                closeButton.click()
                Thread.sleep(1000)
            }
        }
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
