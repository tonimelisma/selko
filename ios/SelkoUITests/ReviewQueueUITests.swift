//
//  ReviewQueueUITests.swift
//  SelkoUITests
//

import XCTest

final class ReviewQueueUITests: XCTestCase {
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
    func testReviewQueueShowsLoadingState() throws {
        app.launch()

        // Navigate past login if needed
        if app.textFields["emailField"].waitForExistence(timeout: 3) {
            app.textFields["emailField"].tap()
            app.textFields["emailField"].typeText("test@selko.local")
            app.secureTextFields["passwordField"].tap()
            app.secureTextFields["passwordField"].typeText("testpass123")
            app.buttons["signInButton"].tap()
        }

        // Should see either loading, integration setup, empty state, or event list
        let loading = app.activityIndicators.firstMatch
        let integrationSetup = app.otherElements["integrationSetupView"]
        let emptyState = app.otherElements["emptyStateView"]
        let eventList = app.tables["eventList"]

        let foundAny = loading.waitForExistence(timeout: 5) ||
            integrationSetup.waitForExistence(timeout: 1) ||
            emptyState.waitForExistence(timeout: 1) ||
            eventList.waitForExistence(timeout: 1)

        XCTAssertTrue(foundAny, "Review queue should display one of its states")
    }

    @MainActor
    func testReviewQueueHasNavigationTitle() throws {
        app.launch()

        // Navigate past login if needed
        if app.textFields["emailField"].waitForExistence(timeout: 3) {
            app.textFields["emailField"].tap()
            app.textFields["emailField"].typeText("test@selko.local")
            app.secureTextFields["passwordField"].tap()
            app.secureTextFields["passwordField"].typeText("testpass123")
            app.buttons["signInButton"].tap()
        }

        // The Review tab should be selected by default
        XCTAssertTrue(app.staticTexts["Review"].waitForExistence(timeout: 5) ||
                       app.navigationBars["Review"].waitForExistence(timeout: 5))
    }
}
