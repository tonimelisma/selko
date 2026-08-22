//
//  UITestSupport.swift
//  SelkoUITests
//

import XCTest

extension XCTestCase {
    /// Signs in from a launch that started with `--selko-reset-session`.
    ///
    /// The old inline version was `if emailField.waitForExistence(timeout: 3)`,
    /// which had two defects. It skipped sign-in entirely whenever the login
    /// screen was slow, so the test continued unauthenticated and failed later
    /// with an unrelated message. And because a session persisted across
    /// launches, it usually skipped sign-in by inheriting whichever user the
    /// previous test had left logged in -- meaning these tests were not really
    /// testing the account they named. Signing out at launch makes the login
    /// screen mandatory, so waiting for it is correct rather than optional.
    @MainActor
    func signIn(
        _ app: XCUIApplication,
        email: String = "test@selko.local",
        password: String = "testpass123",
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let emailField = app.textFields["emailField"]
        XCTAssertTrue(
            emailField.waitForExistence(timeout: 20),
            "Login screen did not appear after session reset",
            file: file,
            line: line
        )
        emailField.tap()
        emailField.typeText(email)

        let passwordField = app.secureTextFields["passwordField"]
        XCTAssertTrue(
            passwordField.waitForExistence(timeout: 5),
            "Password field did not appear",
            file: file,
            line: line
        )
        passwordField.tap()
        passwordField.typeText(password)

        // Typing into a field that is still settling can drop characters, which
        // produces a failed sign-in that looks like a slow backend. Assert what
        // actually landed before submitting.
        if let typed = emailField.value as? String, typed != email {
            emailField.doubleTap()
            app.menuItems["Select All"].firstMatch.tap()
            emailField.typeText(email)
        }

        app.buttons["signInButton"].tap()

        if app.tabBars.firstMatch.waitForExistence(timeout: 20) {
            return
        }

        // One retry: the sign-in button can be tapped while the form is still
        // disabled, in which case nothing was submitted at all.
        if app.buttons["signInButton"].exists {
            app.buttons["signInButton"].tap()
            if app.tabBars.firstMatch.waitForExistence(timeout: 20) {
                return
            }
        }

        XCTFail(
            """
            Main tab view did not appear after signing in as \(email).
            On screen instead:
            \(app.debugDescription)
            """,
            file: file,
            line: line
        )
    }

    /// Taps a tab until its screen settles.
    ///
    /// TabView restores its selection asynchronously after launch and can
    /// overwrite a tap that landed first, so a single tap is not reliable.
    @MainActor
    @discardableResult
    func selectTab(_ app: XCUIApplication, named name: String, expecting element: XCUIElement) -> Bool {
        let tab = app.tabBars.buttons[name]
        guard tab.waitForExistence(timeout: 10) else { return false }
        for _ in 0..<3 {
            tab.tap()
            if element.waitForExistence(timeout: 8) { return true }
        }
        return false
    }
}

/// A session fetched straight from Supabase, handed to the app at launch.
///
/// Driving the login form with simulated typing is the single largest source of
/// flakiness in this suite: a dropped keystroke fails sign-in with "Invalid
/// email or password", and a failed run then costs an extra ~600s while
/// xcodebuild collects simulator diagnostics. Fetching the token over HTTP is
/// deterministic and takes milliseconds.
struct TestSession {
    let accessToken: String
    let refreshToken: String

    static func fetch(
        email: String,
        password: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) -> TestSession? {
        // Local Supabase demo anon key, same value the app ships in DEBUG.
        let anonKey = """
        eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0
        """.trimmingCharacters(in: .whitespacesAndNewlines)

        guard let url = URL(string: "http://127.0.0.1:54321/auth/v1/token?grant_type=password") else {
            return nil
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(anonKey, forHTTPHeaderField: "apikey")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(
            withJSONObject: ["email": email, "password": password]
        )

        var result: TestSession?
        let done = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: request) { data, _, _ in
            defer { done.signal() }
            guard let data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let access = json["access_token"] as? String,
                  let refresh = json["refresh_token"] as? String
            else { return }
            result = TestSession(accessToken: access, refreshToken: refresh)
        }.resume()
        _ = done.wait(timeout: .now() + 15)
        return result
    }

    var launchEnvironment: [String: String] {
        [
            "SELKO_TEST_ACCESS_TOKEN": accessToken,
            "SELKO_TEST_REFRESH_TOKEN": refreshToken,
        ]
    }
}
