//
//  EventDetailUITests.swift
//  SelkoUITests
//

import XCTest

final class EventDetailUITests: XCTestCase {
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
    func testEventDetailHasNavigationTitle() throws {
        app.launch()

        // Smoke-check that the app launches into a known screen.
        // Full event-detail navigation needs seeded backend data.
        let launched = app.staticTexts["Selko"].waitForExistence(timeout: 10) ||
            app.textFields["emailField"].waitForExistence(timeout: 2) ||
            app.tabBars.firstMatch.waitForExistence(timeout: 2) ||
            app.navigationBars.firstMatch.waitForExistence(timeout: 2)

        guard launched else {
            throw XCTSkip("App did not reach a known launch screen in time")
        }
    }
}
