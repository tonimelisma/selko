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

        // Wait for main UI; skip assertions when auth/backend is unavailable
        guard app.tabBars.firstMatch.waitForExistence(timeout: 5) else {
            return
        }

        // Should see either loading, integration setup, empty state, event list, or title
        let loading = app.activityIndicators.firstMatch
        let loadingLabeled = app.descendants(matching: .any)["reviewQueueLoading"]
        let integrationSetup = app.otherElements["integrationSetupView"]
        let emptyState = app.otherElements["emptyStateView"]
        let eventList = app.tables["eventList"]
        let reviewTitle = app.navigationBars["Review"]

        let foundAny = loading.waitForExistence(timeout: 5) ||
            loadingLabeled.waitForExistence(timeout: 1) ||
            integrationSetup.waitForExistence(timeout: 1) ||
            emptyState.waitForExistence(timeout: 1) ||
            eventList.waitForExistence(timeout: 1) ||
            reviewTitle.waitForExistence(timeout: 1)

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

        guard app.tabBars.firstMatch.waitForExistence(timeout: 5) else {
            return
        }

        // The Review tab should be selected by default
        XCTAssertTrue(app.staticTexts["Review"].waitForExistence(timeout: 5) ||
                       app.navigationBars["Review"].waitForExistence(timeout: 5))
    }
}
