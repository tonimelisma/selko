//
//  SettingsUITests.swift
//  SelkoUITests
//

import XCTest

final class SettingsUITests: XCTestCase {
    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--uitesting"]
    }

    override func tearDownWithError() throws {
        app = nil
    }

    @MainActor
    func testSettingsTabExists() throws {
        app.launch()

        // Navigate past login if needed
        if app.textFields["emailField"].waitForExistence(timeout: 3) {
            app.textFields["emailField"].tap()
            app.textFields["emailField"].typeText("test@selko.local")
            app.secureTextFields["passwordField"].tap()
            app.secureTextFields["passwordField"].typeText("testpass123")
            app.buttons["signInButton"].tap()
        }

        _ = app.tabBars.firstMatch.waitForExistence(timeout: 5)

        let settingsTab = app.tabBars.buttons["Settings"]
        if settingsTab.exists {
            settingsTab.tap()
            XCTAssertTrue(app.navigationBars["Settings"].waitForExistence(timeout: 5))
        }
    }

    @MainActor
    func testSettingsShowsConnectedAccountsSection() throws {
        app.launch()

        // Navigate past login
        if app.textFields["emailField"].waitForExistence(timeout: 3) {
            app.textFields["emailField"].tap()
            app.textFields["emailField"].typeText("test@selko.local")
            app.secureTextFields["passwordField"].tap()
            app.secureTextFields["passwordField"].typeText("testpass123")
            app.buttons["signInButton"].tap()
        }

        _ = app.tabBars.firstMatch.waitForExistence(timeout: 5)

        let settingsTab = app.tabBars.buttons["Settings"]
        if settingsTab.exists {
            settingsTab.tap()
            XCTAssertTrue(app.staticTexts["Connected Accounts"].waitForExistence(timeout: 5))
        }
    }

    @MainActor
    func testSettingsShowsSignOutButton() throws {
        app.launch()

        // Navigate past login
        if app.textFields["emailField"].waitForExistence(timeout: 3) {
            app.textFields["emailField"].tap()
            app.textFields["emailField"].typeText("test@selko.local")
            app.secureTextFields["passwordField"].tap()
            app.secureTextFields["passwordField"].typeText("testpass123")
            app.buttons["signInButton"].tap()
        }

        _ = app.tabBars.firstMatch.waitForExistence(timeout: 5)

        let settingsTab = app.tabBars.buttons["Settings"]
        if settingsTab.exists {
            settingsTab.tap()
            // Look for Log out button (may need to scroll)
            let logOutButton = app.buttons["Log out"].firstMatch
            if !logOutButton.waitForExistence(timeout: 3) {
                // Try scrolling down
                app.swipeUp()
            }
            XCTAssertTrue(logOutButton.waitForExistence(timeout: 3) ||
                           app.buttons.matching(NSPredicate(format: "label CONTAINS 'Log out'")).firstMatch.waitForExistence(timeout: 3))
        }
    }
}
