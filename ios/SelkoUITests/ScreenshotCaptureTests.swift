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
    private let pollInterval: TimeInterval = 0.2

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

    @MainActor
    private func waitForAny(
        _ elements: [XCUIElement],
        timeout: TimeInterval,
        description: String
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if elements.contains(where: \.exists) {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(pollInterval))
        } while Date() < deadline

        let found = elements.contains(where: \.exists)
        if !found {
            XCTFail("\(description) did not appear within \(timeout) seconds")
        }
        return found
    }

    @MainActor
    private func revealElement(_ element: XCUIElement, maxSwipes: Int = 3) -> Bool {
        if element.exists {
            return true
        }

        for _ in 0..<maxSwipes {
            app.swipeUp()
            if element.waitForExistence(timeout: 1) {
                return true
            }
        }

        return element.exists
    }

    @MainActor
    private func waitForReviewScreen(timeout: TimeInterval = 15) -> Bool {
        let eventButton = app.buttons.matching(
            NSPredicate(format: "identifier CONTAINS %@", "eventCard")
        ).firstMatch

        return waitForAny(
            [
                app.navigationBars["Review"],
                app.otherElements["integrationSetupView"],
                app.otherElements["emptyStateView"],
                app.tables["eventList"],
                eventButton,
                app.tabBars.buttons["Review"]
            ],
            timeout: timeout,
            description: "Review screen"
        )
    }

    @MainActor
    private func waitForHistoryScreen(timeout: TimeInterval = 10) -> Bool {
        waitForAny(
            [
                app.navigationBars["History"],
                app.otherElements["historyEmptyState"],
                app.tables["historyList"]
            ],
            timeout: timeout,
            description: "History screen"
        )
    }

    @MainActor
    private func waitForSettingsScreen(timeout: TimeInterval = 10) -> Bool {
        waitForAny(
            [
                app.navigationBars["Settings"],
                app.staticTexts["Connected Accounts"],
                app.buttons["signOutButton"]
            ],
            timeout: timeout,
            description: "Settings screen"
        )
    }

    /// If the app is already logged in, sign out first.
    /// The "Log out" button is in the Account section at the bottom of the Settings Form,
    /// so we may need to scroll down to find it.
    @MainActor
    private func ensureLoggedOut() {
        let settingsTab = app.tabBars.buttons["Settings"]
        if settingsTab.waitForExistence(timeout: 3) {
            settingsTab.tap()
            _ = waitForSettingsScreen(timeout: 5)
            let signOutButton = app.buttons["signOutButton"]
            if revealElement(signOutButton) {
                signOutButton.tap()
                XCTAssertTrue(
                    app.textFields["emailField"].waitForExistence(timeout: 10),
                    "Login screen did not appear after sign out"
                )
            }
        }
    }

    // MARK: - Test

    @MainActor
    func testCaptureAllScreenshots() throws {
        // Force portrait orientation regardless of simulator state from previous test runs
        XCUIDevice.shared.orientation = .portrait

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
        XCTAssertTrue(waitForReviewScreen(), "Review screen did not settle after login")

        // 4. Review queue
        saveScreenshot(named: "ios-review-queue")

        // 5. Event detail — tap an event row to trigger the NavigationLink.
        // NavigationLink rows are exposed as Buttons (not cells) in the accessibility hierarchy.
        // Match by identifier containing "eventCard".
        let eventButton = app.buttons.matching(
            NSPredicate(format: "identifier CONTAINS %@", "eventCard")
        ).firstMatch
        if eventButton.waitForExistence(timeout: 5) {
            eventButton.tap()

            // Verify we navigated to event detail
            let detailTitle = app.staticTexts["eventDetailTitle"]
            if detailTitle.waitForExistence(timeout: 5) {
                saveScreenshot(named: "ios-event-detail")

                // Go back to review queue
                let backButton = app.navigationBars.buttons.firstMatch
                if backButton.waitForExistence(timeout: 3) {
                    backButton.tap()
                } else {
                    app.swipeRight()
                }
                XCTAssertTrue(waitForReviewScreen(timeout: 10), "Review screen did not reappear after leaving event detail")
            } else {
                // Navigation didn't work — save current state
                saveScreenshot(named: "ios-event-detail")
            }
        } else {
            // No events — capture current state as placeholder
            saveScreenshot(named: "ios-event-detail")
        }

        // 6. History tab
        let historyTab = app.tabBars.buttons["History"]
        historyTab.tap()
        XCTAssertTrue(waitForHistoryScreen(), "History screen did not appear")
        saveScreenshot(named: "ios-history")

        // 7. Settings tab
        let settingsTab = app.tabBars.buttons["Settings"]
        settingsTab.tap()
        XCTAssertTrue(waitForSettingsScreen(), "Settings screen did not appear")
        saveScreenshot(named: "ios-settings")
    }
}
