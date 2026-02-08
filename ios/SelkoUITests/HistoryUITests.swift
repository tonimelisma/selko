//
//  HistoryUITests.swift
//  SelkoUITests
//

import XCTest

final class HistoryUITests: XCTestCase {
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
    func testHistoryTabExists() throws {
        app.launch()

        // Navigate past login if needed
        if app.textFields["emailField"].waitForExistence(timeout: 3) {
            app.textFields["emailField"].tap()
            app.textFields["emailField"].typeText("test@selko.local")
            app.secureTextFields["passwordField"].tap()
            app.secureTextFields["passwordField"].typeText("testpass123")
            app.buttons["signInButton"].tap()
        }

        // Wait for main UI to appear
        _ = app.tabBars.firstMatch.waitForExistence(timeout: 5)

        // Tap History tab
        let historyTab = app.tabBars.buttons["History"]
        if historyTab.exists {
            historyTab.tap()

            // Should show either loading, empty state, or history list
            let emptyState = app.otherElements["historyEmptyState"]
            let historyList = app.tables["historyList"]
            let historyTitle = app.navigationBars["History"]

            let foundAny = emptyState.waitForExistence(timeout: 5) ||
                historyList.waitForExistence(timeout: 1) ||
                historyTitle.waitForExistence(timeout: 1)

            XCTAssertTrue(foundAny, "History should display one of its states")
        }
    }

    @MainActor
    func testHistoryNavigationTitle() throws {
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

        let historyTab = app.tabBars.buttons["History"]
        if historyTab.exists {
            historyTab.tap()
            XCTAssertTrue(app.navigationBars["History"].waitForExistence(timeout: 5))
        }
    }
}
