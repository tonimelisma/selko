//
//  ScreenshotCaptureTests.swift
//  iOSUITests
//
//  Navigates through all 6 screens and saves PNG screenshots to docs/screenshots/.
//  Run with: xcodebuild test -project ios/iOS.xcodeproj -scheme iOS \
//    -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
//    -only-testing:iOSUITests/ScreenshotCaptureTests
//

import XCTest

final class ScreenshotCaptureTests: XCTestCase {
    var app: XCUIApplication!

    /// Resolve the project-root docs/screenshots directory.
    /// The test source lives at <project>/ios/SelkoUITests/ScreenshotCaptureTests.swift,
    /// so we go up three levels to reach the project root.
    private var screenshotDir: String {
        let thisFile = URL(fileURLWithPath: #filePath)
        let projectRoot = thisFile
            .deletingLastPathComponent()  // SelkoUITests/
            .deletingLastPathComponent()  // ios/
            .deletingLastPathComponent()  // project root
        return projectRoot.appendingPathComponent("docs/screenshots").path
    }

    override func setUpWithError() throws {
        // Keep going after a failure so we capture as many screenshots as possible
        continueAfterFailure = true
        app = XCUIApplication()
    }

    override func tearDownWithError() throws {
        app = nil
    }

    // MARK: - Helpers

    /// Take a screenshot and save to docs/screenshots/.
    /// The wrapper script handles resizing to ≤1920px after the test completes.
    private func saveScreenshot(named name: String) {
        let screenshot = app.screenshot()
        let pngData = screenshot.pngRepresentation

        // Ensure output directory exists
        try? FileManager.default.createDirectory(
            atPath: screenshotDir,
            withIntermediateDirectories: true
        )

        let filePath = (screenshotDir as NSString).appendingPathComponent("\(name).png")
        do {
            try pngData.write(to: URL(fileURLWithPath: filePath))
        } catch {
            XCTFail("Failed to write screenshot \(name): \(error)")
        }
    }

    /// If the app is already logged in, sign out first.
    @MainActor
    private func ensureLoggedOut() {
        let settingsTab = app.tabBars.buttons["Settings"]
        if settingsTab.waitForExistence(timeout: 3) {
            settingsTab.tap()
            sleep(1)
            let signOutButton = app.buttons["signOutButton"]
            if signOutButton.waitForExistence(timeout: 3) {
                signOutButton.tap()
                sleep(2)
            }
        }
    }

    // MARK: - Test

    @MainActor
    func testCaptureAllScreenshots() throws {
        app.launch()

        // Handle case where app is already logged in from a previous run
        let emailField = app.textFields["emailField"]
        if !emailField.waitForExistence(timeout: 5) {
            // Already logged in — sign out first
            ensureLoggedOut()
            XCTAssertTrue(emailField.waitForExistence(timeout: 10), "Login screen did not appear after sign out")
        }

        // 1. Login screen
        saveScreenshot(named: "ios-login")

        // 2. Register screen (modal)
        app.buttons["createAccountButton"].tap()
        let registerEmail = app.textFields["registerEmailField"]
        XCTAssertTrue(registerEmail.waitForExistence(timeout: 5), "Register sheet did not appear")
        saveScreenshot(named: "ios-register")

        // Dismiss register sheet
        let cancelButton = app.buttons["Cancel"]
        if cancelButton.waitForExistence(timeout: 2) {
            cancelButton.tap()
        } else {
            // Swipe down to dismiss the full-screen cover
            app.swipeDown(velocity: .fast)
        }

        // Wait for login screen to be back
        XCTAssertTrue(emailField.waitForExistence(timeout: 5), "Login screen did not reappear after dismissing register")

        // 3. Log in with seed user
        emailField.tap()
        emailField.typeText("screenshots@selko.local")

        let passwordField = app.secureTextFields["passwordField"]
        passwordField.tap()
        passwordField.typeText("screenshotpass123")

        app.buttons["signInButton"].tap()

        // Wait for the main tab view to appear (review queue loads)
        let reviewTab = app.tabBars.buttons["Review"]
        XCTAssertTrue(reviewTab.waitForExistence(timeout: 15), "Main tab view did not appear after login")

        // Give data time to load
        sleep(3)

        // 4. Review queue
        saveScreenshot(named: "ios-review-queue")

        // 5. Event detail — tap the "Edit" button on first event card
        // The Edit button is inside a NavigationLink, tapping it navigates to detail
        let editButton = app.buttons.matching(identifier: "eventCard").matching(NSPredicate(format: "label == 'Edit'")).firstMatch
        if editButton.waitForExistence(timeout: 5) {
            // Use coordinate-based tap to work around NavigationLink hit testing
            let coordinate = editButton.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
            coordinate.tap()
            sleep(2)
            saveScreenshot(named: "ios-event-detail")

            // Go back to review queue — try Back button, then navigation bar button
            let backButton = app.navigationBars.buttons["Back"]
            if backButton.waitForExistence(timeout: 2) {
                backButton.tap()
            } else {
                // Tap first button in navigation bar as fallback
                let navButton = app.navigationBars.buttons.firstMatch
                if navButton.waitForExistence(timeout: 2) {
                    navButton.tap()
                } else {
                    // Swipe right to go back
                    app.swipeRight()
                }
            }
            sleep(1)
        } else {
            // No events — capture current state as placeholder
            saveScreenshot(named: "ios-event-detail")
        }

        // 6. History tab
        let historyTab = app.tabBars.buttons["History"]
        historyTab.tap()
        sleep(2)
        saveScreenshot(named: "ios-history")

        // 7. Settings tab
        let settingsTab = app.tabBars.buttons["Settings"]
        settingsTab.tap()
        sleep(1)
        saveScreenshot(named: "ios-settings")
    }
}
