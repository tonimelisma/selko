//
//  Config.swift
//  Selko
//
//  Created by Claude on 1/26/26.
//

import Foundation

enum Config {
    static var supabaseURL: String {
        // For development, use staging Supabase
        // TODO: Switch to production URL for release builds
        #if DEBUG
        return "https://lxmysergoeaegxlyfzwk.supabase.co"
        #else
        return "https://khahcozfbnpykspvatrg.supabase.co"
        #endif
    }

    static var supabaseAnonKey: String {
        // These are public anon keys (safe to include in client apps)
        // They only provide access via RLS policies
        #if DEBUG
        // Staging anon key
        return ProcessInfo.processInfo.environment["SUPABASE_ANON_KEY"] ?? ""
        #else
        // Production anon key
        return ProcessInfo.processInfo.environment["SUPABASE_ANON_KEY"] ?? ""
        #endif
    }
}
