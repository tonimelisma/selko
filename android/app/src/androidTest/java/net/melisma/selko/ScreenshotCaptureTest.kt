package net.melisma.selko

import android.graphics.Bitmap
import android.os.Environment
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.BySelector
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.io.FileOutputStream

/**
 * Navigates through all 6 screens in light and dark appearances and saves 12 PNG screenshots.
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
        private const val POLL_INTERVAL = 250L
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

        device.executeShellCommand("cmd uimode night no")

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
        device.waitForIdle()
        saveScreenshot("android-login-light")

        // 2. Register screen
        val signUpToggle = device.wait(
            Until.findObject(By.text("Don't have an account? Sign up")), SHORT_TIMEOUT
        )
        requireNotNull(signUpToggle) { "Could not find 'Sign up' toggle on login screen" }
        (signUpToggle.parent ?: signUpToggle).click()
        device.wait(Until.hasObject(By.text("Confirm password")), SHORT_TIMEOUT)
        device.waitForIdle()
        saveScreenshot("android-register-light")

        // Go back to login
        val loginToggle = device.wait(
            Until.findObject(By.text("Already have an account? Log in")), SHORT_TIMEOUT
        )
        requireNotNull(loginToggle) { "Could not find 'Log in' toggle on register screen" }
        (loginToggle.parent ?: loginToggle).click()
        device.wait(Until.hasObject(By.text("Sign in")), SHORT_TIMEOUT)
        device.waitForIdle()

        // 3. Log in with seed user (retry up to 3 times — cold-booted emulator networking
        //    may not be ready, causing Supabase auth timeouts)
        var loggedIn = false
        for (attempt in 1..3) {
            val emailLabel = device.wait(Until.findObject(By.text("Email")), SHORT_TIMEOUT)
            requireNotNull(emailLabel) { "Could not find Email field on login screen (attempt $attempt)" }
            val emailField = requireNotNull(emailLabel.parent) { "Email field container missing (attempt $attempt)" }
            emailField.click()
            device.waitForIdle()
            emailField.text = SCREENSHOT_USER

            val passwordLabel = device.wait(Until.findObject(By.text("Password")), SHORT_TIMEOUT)
            requireNotNull(passwordLabel) { "Could not find Password field on login screen (attempt $attempt)" }
            val passwordField = requireNotNull(passwordLabel.parent) { "Password field container missing (attempt $attempt)" }
            passwordField.click()
            device.waitForIdle()
            passwordField.text = SCREENSHOT_PASS

            // Try to find Sign in button; dismiss keyboard first if it's blocking
            device.waitForIdle()
            var signInButton = waitForObject(By.text("Sign in"), SHORT_TIMEOUT / 2)
            if (signInButton == null) {
                // Keyboard may be covering the button — dismiss it
                device.pressBack()
                device.waitForIdle()
                signInButton = waitForObject(By.text("Sign in"))
            }
            requireNotNull(signInButton) { "Could not find Sign in button (attempt $attempt)" }
            signInButton.click()

            // Wait for the review queue to load
            loggedIn = waitForReviewScreen(TIMEOUT * 2)
            if (loggedIn) break

            require(waitForAnyObject(SHORT_TIMEOUT, By.text("Email"), By.text("Sign in"))) {
                "Login attempt $attempt did not return to the login form"
            }
        }
        require(loggedIn) { "Failed to log in after 3 attempts — check emulator networking and Supabase" }
        device.waitForIdle()

        // 4. Review queue
        saveScreenshot("android-review-queue-light")

        // 5. History tab
        tapAndAwaitScreen("History", "History screen") { waitForHistoryScreen() }
        saveScreenshot("android-history-light")

        // 6. Settings tab
        tapAndAwaitScreen("Settings", "Settings screen") { waitForSettingsScreen() }
        saveScreenshot("android-settings-light")

        // 7. Go back to Review tab, then navigate to event detail
        tapAndAwaitScreen("Review", "Review screen") { waitForReviewScreen() }

        val editButton = waitForObject(By.text("Edit")) ?: waitForObject(By.desc("Edit"))
        if (editButton != null) {
            editButton.click()
            require(waitForAnyObject(SHORT_TIMEOUT, By.text("Event Details"))) {
                "Event details screen did not appear"
            }
            device.waitForIdle()
        }
        saveScreenshot("android-event-detail-light")

        captureDarkScreenshots()
    }

    private fun captureDarkScreenshots() {
        device.executeShellCommand("cmd uimode night yes")
        SystemClock.sleep(1_500)
        device.waitForIdle()
        // The activity is recreated for the appearance change and returns to its
        // authenticated Review start destination. Capture from that stable state.
        require(waitForReviewScreen()) { "Dark Review screen did not appear after appearance change" }
        saveScreenshot("android-review-queue-dark")

        val edit = waitForObject(By.text("Edit")) ?: waitForObject(By.desc("Edit"))
        requireNotNull(edit) { "Could not find Edit action in dark Review" }
        edit.click()
        require(waitForAnyObject(SHORT_TIMEOUT, By.text("Event Details"))) { "Dark Event Details did not appear" }
        device.waitForIdle()
        saveScreenshot("android-event-detail-dark")

        val back = waitForObject(By.desc("Back"))
        if (back != null) back.click() else device.click(64, 180)
        require(waitForReviewScreen()) { "Review screen did not appear after leaving dark Event Detail" }

        tapAndAwaitScreen("History", "History screen") { waitForHistoryScreen() }
        saveScreenshot("android-history-dark")

        tapAndAwaitScreen("Settings", "Settings screen") { waitForSettingsScreen() }
        saveScreenshot("android-settings-dark")

        var logout = waitForObject(By.text("Log out"), 1_000)
        repeat(5) {
            if (logout == null) {
                device.swipe(device.displayWidth / 2, device.displayHeight * 3 / 4, device.displayWidth / 2, device.displayHeight / 4, 500)
                device.waitForIdle()
                logout = waitForObject(By.text("Log out"), 1_000)
            }
        }
        requireNotNull(logout) { "Could not find Settings Log out action" }
        // The text node is a child of the semantic button; click its clickable
        // parent so the action is dispatched consistently by UIAutomator.
        (logout.parent ?: logout).click()
        require(device.wait(Until.gone(By.text("Settings")), TIMEOUT)) {
            "Authenticated navigation did not disappear after logout"
        }
        require(waitForAnyObject(TIMEOUT, By.text("Sign in"))) { "Login screen did not appear after logout" }
        SystemClock.sleep(500)
        device.waitForIdle()
        saveScreenshot("android-login-dark")

        val signUpToggle = waitForObject(By.text("Don't have an account? Sign up"))
        requireNotNull(signUpToggle) { "Could not find dark-mode sign-up toggle" }
        (signUpToggle.parent ?: signUpToggle).click()
        require(waitForAnyObject(SHORT_TIMEOUT, By.text("Confirm password"))) { "Dark register screen did not appear" }
        SystemClock.sleep(500)
        device.waitForIdle()
        saveScreenshot("android-register-dark")

        device.executeShellCommand("cmd uimode night no")
    }

    private fun waitForObject(selector: BySelector, timeout: Long = SHORT_TIMEOUT): UiObject2? {
        return device.wait(Until.findObject(selector), timeout)
    }

    private fun waitForAnyObject(timeout: Long = SHORT_TIMEOUT, vararg selectors: BySelector): Boolean {
        val deadline = SystemClock.elapsedRealtime() + timeout
        while (SystemClock.elapsedRealtime() < deadline) {
            if (selectors.any(device::hasObject)) {
                return true
            }
            device.waitForIdle(POLL_INTERVAL)
        }
        return selectors.any(device::hasObject)
    }

    private fun waitForReviewScreen(timeout: Long = TIMEOUT): Boolean {
        return waitForAnyObject(
            timeout,
            By.text("Review Queue"),
            By.text("New"),
            By.text("Changes"),
            By.text("All caught up!"),
            By.text("Welcome to Selko"),
            By.text("Connect Google Account"),
            By.text("Edit")
        )
    }

    private fun waitForHistoryScreen(timeout: Long = SHORT_TIMEOUT): Boolean {
        return waitForAnyObject(
            timeout,
            By.text("Activity History"),
            By.text("No Activity Yet"),
            By.text("Load More"),
            By.text("Undo"),
            By.text("Retry")
        )
    }

    private fun waitForSettingsScreen(timeout: Long = SHORT_TIMEOUT): Boolean {
        // "Settings" is always present in the bottom navigation, so it cannot
        // prove the destination has finished composing. Wait for page-only
        // content before capturing to avoid saving the previous screen.
        return waitForAnyObject(timeout, By.text("CONNECTED ACCOUNTS"), By.text("ACCOUNT"))
    }

    private fun tapAndAwaitScreen(
        label: String,
        description: String,
        waitForScreen: () -> Boolean
    ) {
        // Use By.text() to find the label Text composable.  Clicking the Text child
        // of a Compose NavigationBarItem propagates the click to the item's onClick.
        // (By.desc() finds the Icon child, whose click does NOT propagate.)
        val tab = waitForObject(By.text(label))
        requireNotNull(tab) { "Could not find '$label' tab" }
        tab.click()
        require(waitForScreen()) { "$description did not appear after tapping '$label'" }
    }

    private fun dismissSystemDialogs() {
        // Repeatedly dismiss "System UI isn't responding" and similar dialogs
        repeat(3) {
            val waitButton = device.findObject(By.text("Wait"))
            if (waitButton != null) {
                waitButton.click()
                device.wait(Until.gone(By.text("Wait")), SHORT_TIMEOUT)
            }
            val closeButton = device.findObject(By.text("Close app"))
            if (closeButton != null) {
                closeButton.click()
                device.wait(Until.gone(By.text("Close app")), SHORT_TIMEOUT)
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
