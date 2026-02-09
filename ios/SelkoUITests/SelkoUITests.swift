//
//  SelkoUITests.swift
//  SelkoUITests
//
//  Created by Toni Melisma on 1/26/26.
//

import XCTest

final class SelkoUITests: XCTestCase {
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
    func testLoginScreenDisplaysCorrectElements() throws {
        app.launch()

        // Verify login screen elements are present
        XCTAssertTrue(app.staticTexts["Selko"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.textFields["emailField"].exists)
        XCTAssertTrue(app.secureTextFields["passwordField"].exists)
        XCTAssertTrue(app.buttons["signInButton"].exists)
        XCTAssertTrue(app.buttons["createAccountButton"].exists)
    }

    @MainActor
    func testCreateAccountButtonOpensRegisterSheet() throws {
        app.launch()

        // Tap create account button
        app.buttons["createAccountButton"].tap()

        // Verify register sheet appears
        XCTAssertTrue(app.staticTexts["Sign up"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.textFields["registerEmailField"].exists)
        XCTAssertTrue(app.secureTextFields["registerPasswordField"].exists)
        XCTAssertTrue(app.secureTextFields["confirmPasswordField"].exists)
        XCTAssertTrue(app.buttons["registerButton"].exists)
    }

    @MainActor
    func testLoginWithEmptyFieldsShowsError() throws {
        app.launch()

        // Tap sign in without entering credentials
        app.buttons["signInButton"].tap()

        // Verify error message appears
        XCTAssertTrue(app.staticTexts["errorMessage"].waitForExistence(timeout: 2))
    }

    @MainActor
    func testCanEnterCredentials() throws {
        app.launch()

        // Enter email
        let emailField = app.textFields["emailField"]
        emailField.tap()
        emailField.typeText("test@example.com")

        // Enter password
        let passwordField = app.secureTextFields["passwordField"]
        passwordField.tap()
        passwordField.typeText("password123")

        // Verify the values were entered (email field shows the text)
        XCTAssertEqual(emailField.value as? String, "test@example.com")
    }

    @MainActor
    func testRegisterValidationShowsPasswordMismatchError() throws {
        app.launch()

        // Open register sheet
        app.buttons["createAccountButton"].tap()

        // Wait for sheet to appear
        XCTAssertTrue(app.staticTexts["Sign up"].waitForExistence(timeout: 5))

        // Enter email
        let emailField = app.textFields["registerEmailField"]
        emailField.tap()
        emailField.typeText("test@example.com")

        // Enter password
        let passwordField = app.secureTextFields["registerPasswordField"]
        passwordField.tap()
        passwordField.typeText("password123")

        // Enter different confirm password
        let confirmField = app.secureTextFields["confirmPasswordField"]
        confirmField.tap()
        confirmField.typeText("differentpassword")

        // Tap register
        app.buttons["registerButton"].tap()

        // Verify error message appears
        XCTAssertTrue(app.staticTexts["registerErrorMessage"].waitForExistence(timeout: 2))
    }

    @MainActor
    func testLaunchPerformance() throws {
        measure(metrics: [XCTApplicationLaunchMetric()]) {
            XCUIApplication().launch()
        }
    }
}
