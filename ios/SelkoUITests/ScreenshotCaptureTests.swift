//
//  ScreenshotCaptureTests.swift
//  iOSUITests
//
//  Navigates through all 6 screens and saves appearance-specific PNG screenshots.
//  Run with: xcodebuild test -project ios/iOS.xcodeproj -scheme iOS \
//    -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
//    -only-testing:iOSUITests/ScreenshotCaptureTests
//

import XCTest

final class ScreenshotCaptureTests: XCTestCase {
    var app: XCUIApplication!
    private let pollInterval: TimeInterval = 0.2

    private var appearance = "light"

    /// Resolve the project-root docs/screenshots directory.
    /// Prefer SCREENSHOT_DIR from the launch environment (set by capture-ios-screenshots.sh)
    /// so worktrees always write to the correct tree.
    private var screenshotDir: String {
        if let envDir = ProcessInfo.processInfo.environment["SCREENSHOT_DIR"], !envDir.isEmpty {
            return envDir
        }
        let thisFile = URL(fileURLWithPath: #filePath)
        let projectRoot = thisFile
            .deletingLastPathComponent()  // SelkoUITests/
            .deletingLastPathComponent()  // ios/
            .deletingLastPathComponent()  // project root
        return projectRoot.appendingPathComponent("docs/screenshots").path
    }

    override func setUpWithError() throws {
        // Fail fast — wrong-screen screenshots are worse than a failed capture run
        continueAfterFailure = false
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

        let filePath = (screenshotDir as NSString).appendingPathComponent("\(name)-\(appearance).png")
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
        description: String,
        failOnTimeout: Bool = true
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if elements.contains(where: \.exists) {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(pollInterval))
        } while Date() < deadline

        let found = elements.contains(where: \.exists)
        if !found && failOnTimeout {
            // Dump what IS on screen. Without this the failure says only that
            // an expected element is absent, which is the least useful half of
            // the information -- three wrong diagnoses were made from it.
            XCTFail("""
                \(description) did not appear within \(timeout) seconds.
                On screen instead:
                \(app.debugDescription)
                """)
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
    private func waitForReviewScreen(
        timeout: TimeInterval = 15,
        failOnTimeout: Bool = true
    ) -> Bool {
        // Do NOT treat the Review tab button as success — it exists on every tab.
        // An event card is identified by its title text; the card itself is not
        // a button and carries no identifier of its own.
        let eventButton = app.staticTexts["eventTitle"].firstMatch

        return waitForAny(
            [
                app.navigationBars["Review"],
                app.otherElements["integrationSetupView"],
                app.otherElements["emptyStateView"],
                app.scrollViews["emptyStateView"],
                // ReviewQueueView's eventList is a SwiftUI List. Since iOS 16
                // that is backed by UICollectionView, so it surfaces as
                // `collectionViews`, not `tables`. Matching only tables and
                // otherElements meant a fully-populated Review screen was
                // invisible to this wait and the test timed out on a screen
                // that had rendered correctly.
                app.collectionViews["eventList"],
                app.tables["eventList"],
                app.otherElements["eventList"],
                eventButton
            ],
            timeout: timeout,
            description: "Review screen",
            failOnTimeout: failOnTimeout
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
    func testCaptureLightScreenshots() throws {
        try captureAllScreenshots(appearance: "light")
    }

    @MainActor
    func testCaptureDarkScreenshots() throws {
        try captureAllScreenshots(appearance: "dark")
    }

    @MainActor
    private func captureAllScreenshots(appearance: String) throws {
        self.appearance = appearance
        // Force portrait orientation regardless of simulator state from previous test runs
        XCUIDevice.shared.orientation = .portrait

        app.launchArguments = ["--selko-screenshot-appearance", appearance, "--selko-reset-session"]
        app.launch()

        let appearanceProbe = app.otherElements["screenshotAppearanceProbe"]
        XCTAssertTrue(
            appearanceProbe.waitForExistence(timeout: 5),
            "Appearance probe did not appear"
        )
        XCTAssertEqual(
            appearanceProbe.value as? String,
            appearance,
            "App did not render in the requested \(appearance) appearance"
        )

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

        // 3. Become authenticated by installing a session, not by typing.
        //
        // Simulated typing into the login form was this suite's largest source
        // of flakiness: a dropped keystroke fails sign-in with "Invalid email
        // or password", and each failed run then cost ~600s while xcodebuild
        // collected simulator diagnostics. The login form itself is still
        // covered by SelkoUITests, which drives it directly.
        guard let session = TestSession.fetch(
            email: "screenshots@selko.local",
            password: "screenshotpass123"
        ) else {
            XCTFail("Could not obtain a session from local Supabase at 127.0.0.1:54321")
            return
        }

        app.terminate()
        app.launchEnvironment = session.launchEnvironment
        app.launch()

        let reviewTab = app.tabBars.buttons["Review"]
        XCTAssertTrue(
            reviewTab.waitForExistence(timeout: 20),
            """
            Main tab view did not appear with an injected session.
            On screen instead:
            \(app.debugDescription)
            """
        )

        // Tap until it takes. `app.launch()` does not reset app state, so the
        // TabView restores whichever tab the previous run left selected -- and
        // that restoration races this tap. When Settings won the race the test
        // failed with "Review screen did not appear", which reads like a data
        // or query problem and is not one; the element dump on failure now
        // shows `NavigationBar identifier: 'Settings'` and says so plainly.
        var landedOnReview = false
        for _ in 0..<3 {
            reviewTab.tap()
            if waitForReviewScreen(timeout: 8, failOnTimeout: false) {
                landedOnReview = true
                break
            }
        }
        XCTAssertTrue(landedOnReview, "Review screen did not settle after login")
        // Loading can leave the nav title visible before content is ready — wait for content.
        let loading = app.otherElements["reviewQueueLoading"]
        if loading.exists {
            _ = loading.waitForExistence(timeout: 0) // already exists
            let deadline = Date().addingTimeInterval(15)
            while loading.exists && Date() < deadline {
                RunLoop.current.run(until: Date().addingTimeInterval(pollInterval))
            }
        }
        XCTAssertTrue(
            app.navigationBars["Review"].waitForExistence(timeout: 5),
            "Expected Review navigation bar before capturing review queue"
        )
        XCTAssertFalse(
            app.navigationBars["Settings"].exists,
            "Must not capture Settings as the review queue"
        )

        // 4. Review queue
        saveScreenshot(named: "ios-review-queue")

        // Accessibility contract for the review card, folded in from the
        // deleted ReviewQueueUITests: each action is individually labeled with
        // its event's title (so VoiceOver users can tell three "Accept" buttons
        // apart) and meets the 48pt target from design/tokens.json. Asserted
        // here because this test is already signed in and on this screen --
        // the deleted test spent ~24s re-reaching it to assert the same thing.
        let eventTitle = app.staticTexts["eventTitle"].firstMatch
        XCTAssertTrue(eventTitle.waitForExistence(timeout: 10), "No event card in the review queue")
        let cardTitle = eventTitle.label
        XCTAssertFalse(app.buttons["eventCard"].exists, "The card itself must not be a button")
        for action in ["Accept ", "Edit ", "Reject "] {
            // Match on the event title too: the screen also has a bulk
            // "Accept all" button, which BEGINSWITH "Accept " but names no event.
            let button = app.buttons.matching(
                NSPredicate(format: "label BEGINSWITH %@ AND label CONTAINS %@", action, cardTitle)
            ).firstMatch
            XCTAssertTrue(
                button.exists,
                "No \(action)action naming \(cardTitle) on the review card"
            )
            // Round before comparing: SwiftUI lays a 48pt control out as
            // 47.99999999999994, and an exact >= 48 comparison fails a control
            // that meets the spec. The tolerance is float noise, not slack in
            // the requirement.
            XCTAssertGreaterThanOrEqual(
                button.frame.height.rounded(),
                48,
                "\(action)target below 48pt (measured \(button.frame.height))"
            )
        }

        // 5. Event detail
        // Detail opens from the card's Edit button, not from the card body.
        // ReviewQueueView passes `onEdit: { onNavigateToEvent(event.id) }`, and
        // eventCardContainer is a plain VStack with no tap gesture or
        // NavigationLink -- so tapping its upper area, as this did, lands on
        // dead space and the test waited 10s for a push that was never going
        // to happen.
        let editButton = app.buttons.matching(
            NSPredicate(format: "label BEGINSWITH %@", "Edit ")
        ).firstMatch
        XCTAssertTrue(
            editButton.waitForExistence(timeout: 5),
            "No Edit action on the event card to open detail with"
        )
        editButton.tap()

        // Title is a TextField (accessibility id eventDetailTitle), not a StaticText
        let detailAppeared = waitForAny(
            [
                app.navigationBars["Event Detail"],
                app.textFields["eventDetailTitle"]
            ],
            timeout: 10,
            description: "Event detail"
        )
        XCTAssertTrue(detailAppeared, "Event detail did not appear")
        saveScreenshot(named: "ios-event-detail")

        // Go back to review queue
        let backButton = app.navigationBars.buttons.firstMatch
        if backButton.waitForExistence(timeout: 3) {
            backButton.tap()
        } else {
            app.swipeRight()
        }
        XCTAssertTrue(waitForReviewScreen(timeout: 10), "Review screen did not reappear after leaving event detail")

        // 6. History tab
        let historyTab = app.tabBars.buttons["History"]
        historyTab.tap()
        XCTAssertTrue(waitForHistoryScreen(), "History screen did not appear")
        XCTAssertFalse(app.buttons["Synced"].exists, "Static history status must not be exposed as a button")
        XCTAssertTrue(app.staticTexts["Synced"].waitForExistence(timeout: 3))
        let undoButton = app.buttons["undoButton"].firstMatch
        XCTAssertTrue(undoButton.waitForExistence(timeout: 3))
        XCTAssertGreaterThanOrEqual(
            undoButton.frame.height.rounded(),
            44,
            "Undo target below 44pt (measured \(undoButton.frame.height))"
        )
        saveScreenshot(named: "ios-history")

        // 7. Settings tab
        let settingsTab = app.tabBars.buttons["Settings"]
        settingsTab.tap()
        XCTAssertTrue(waitForSettingsScreen(), "Settings screen did not appear")
        XCTAssertTrue(
            app.staticTexts["Email Folders"].waitForExistence(timeout: 15),
            "Email-folder content did not finish loading"
        )
        // Connected Accounts is asserted here, at the top of Settings and
        // before any scrolling: a SwiftUI Form is a UICollectionView, so once
        // the folder rows are scrolled into view these rows may no longer be
        // instantiated. Folded in from the deleted SettingsUITests, which paid
        // a full sign-in to reach this same screen.
        XCTAssertTrue(
            app.staticTexts["integrationName_gmail"].exists
                || app.staticTexts["integrationName_outlook"].exists,
            "Connected Accounts section rendered no provider rows"
        )

        // Capture before scrolling so the committed screenshot always shows
        // the top of Settings.
        saveScreenshot(named: "ios-settings")

        // A SwiftUI Form is a UICollectionView, so rows below the fold are
        // never instantiated and are genuinely absent from the accessibility
        // tree -- waiting cannot conjure them, which is why a 15s timeout
        // behaved exactly like a 5s one. Scroll the folder rows into view the
        // same way the sign-out assertion does.
        //
        // Assert the switch and its label rather than a bare StaticText: the
        // include/exclude wording belongs to the Toggle, and tokens.json
        // specifies this control as a *labeled switch*.
        let folderSwitches = app.switches.matching(
            NSPredicate(format: "identifier BEGINSWITH %@", "folderToggle_")
        )
        for _ in 0..<6 where folderSwitches.firstMatch.exists == false {
            app.swipeUp()
        }
        if !folderSwitches.firstMatch.waitForExistence(timeout: 5) {
            XCTFail(
                """
                No folder toggle rendered in the Email Folders section.
                Switches: \(app.switches.count)
                Elements on screen:
                \(app.debugDescription)
                """
            )
        }

        // Folded in from the deleted SettingsUITests: the sign-out target meets
        // 44pt. It sits at the bottom of the Form, so this runs after the
        // folder rows have already been scrolled into view.
        let signOut = app.buttons["signOutButton"]
        for _ in 0..<6 where !signOut.exists {
            app.swipeUp()
        }
        XCTAssertTrue(signOut.waitForExistence(timeout: 3), "Log out button never appeared")
        XCTAssertGreaterThanOrEqual(
            signOut.frame.height.rounded(),
            44,
            "Log out target below 44pt (measured \(signOut.frame.height))"
        )

        // Every rendered toggle must state its include/exclude status. Only the
        // rows the Form has currently instantiated are in the tree, so asserting
        // that *both* states appear at once depends on scroll position rather
        // than on behaviour -- the run that failed here had scrolled past the
        // included folder and saw only the excluded one.
        let states = folderSwitches.allElementsBoundByIndex.map(\.label)
        XCTAssertFalse(states.isEmpty, "No folder toggles rendered")
        for state in states {
            XCTAssertTrue(
                state.contains("Included") || state.contains("Excluded"),
                "Folder toggle must state its include/exclude status; label was \(state)"
            )
        }
    }
}
