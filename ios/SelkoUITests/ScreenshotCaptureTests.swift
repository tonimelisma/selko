//
//  ScreenshotCaptureTests.swift
//  SelkoUITests
//
//  Navigates through all 6 screens and saves PNG screenshots to docs/screenshots/.
//  Run with: xcodebuild test -project ios/iOS.xcodeproj -scheme iOS \
//    -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
//    -only-testing:SelkoUITests/ScreenshotCaptureTests
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
        app.launchArguments = ["--uitesting"]
    }

    override func tearDownWithError() throws {
        app = nil
    }

    // MARK: - Helpers

    /// Take a screenshot, resize to ≤1920px height, and save to docs/screenshots/.
    private func saveScreenshot(named name: String) {
        let screenshot = app.screenshot()
        let image = screenshot.image

        // Resize if taller than 1920px (iPhone 17 Pro is 2796px native)
        let maxHeight: CGFloat = 1920
        let resized: Data? = {
            guard image.size.height > maxHeight else {
                return screenshot.pngRepresentation
            }
            let scale = maxHeight / image.size.height
            let newSize = CGSize(width: image.size.width * scale, height: maxHeight)
            let renderer = UIGraphicsImageRenderer(size: newSize)
            let resizedImage = renderer.image { _ in
                image.draw(in: CGRect(origin: .zero, size: newSize))
            }
            return resizedImage.pngData()
        }()

        guard let pngData = resized else {
            XCTFail("Failed to create PNG data for \(name)")
            return
        }

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

    // MARK: - Test

    @MainActor
    func testCaptureAllScreenshots() throws {
        app.launch()

        // 1. Login screen
        let emailField = app.textFields["emailField"]
        XCTAssertTrue(emailField.waitForExistence(timeout: 10), "Login screen did not appear")
        saveScreenshot(named: "ios-login")

        // 2. Register screen (modal)
        app.buttons["createAccountButton"].tap()
        let registerEmail = app.textFields["registerEmailField"]
        XCTAssertTrue(registerEmail.waitForExistence(timeout: 5), "Register sheet did not appear")
        saveScreenshot(named: "ios-register")

        // Dismiss register sheet
        // Look for Cancel / close button in the navigation bar
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
        sleep(2)

        // 4. Review queue
        saveScreenshot(named: "ios-review-queue")

        // 5. Event detail — tap the first event card
        let firstEventCard = app.buttons.matching(identifier: "eventCard").firstMatch
        if firstEventCard.waitForExistence(timeout: 5) {
            firstEventCard.tap()
            // Wait for detail view to load
            sleep(1)
            saveScreenshot(named: "ios-event-detail")

            // Go back to review queue
            app.navigationBars.buttons.firstMatch.tap()
            sleep(1)
        } else {
            // No events — capture empty state as event detail placeholder
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
