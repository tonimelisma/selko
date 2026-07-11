/**
 * @typedef {Object} User
 * @property {string} id - UUID
 * @property {string} email
 * @property {string} [display_name]
 * @property {string} created_at
 * @property {string} updated_at
 */

/**
 * @typedef {'gmail' | 'google_photos' | 'google_calendar'} IntegrationProvider
 */

/**
 * @typedef {'active' | 'expired' | 'revoked' | 'error'} IntegrationStatus
 */

/**
 * @typedef {Object} Integration
 * @property {string} id - UUID
 * @property {string} user_id - UUID
 * @property {IntegrationProvider} provider
 * @property {IntegrationStatus} status
 * @property {string} [provider_email]
 * @property {string[]} scopes
 * @property {string} [last_sync_at]
 * @property {string} created_at
 * @property {string} updated_at
 */

/**
 * @typedef {Object} Email
 * @property {string} id - UUID
 * @property {string} user_id - UUID
 * @property {string} [integration_id] - UUID
 * @property {string} gmail_id
 * @property {string} [thread_id]
 * @property {string} [subject]
 * @property {string} [from_email]
 * @property {string} [from_name]
 * @property {string[]} [to_emails]
 * @property {string} [date_sent]
 * @property {string} [snippet]
 * @property {string[]} gmail_label_ids
 * @property {boolean} is_spam
 * @property {boolean} is_trash
 * @property {boolean} is_promotions
 * @property {boolean} is_social
 * @property {boolean} is_updates
 * @property {boolean} is_forums
 * @property {boolean} is_primary
 * @property {boolean} is_important
 * @property {boolean} is_starred
 * @property {boolean} is_unread
 * @property {boolean} has_attachments
 * @property {string} [processing_status]
 * @property {string} created_at
 */

/**
 * @typedef {'pending_review' | 'pending_change' | 'approved' | 'syncing' | 'synced' | 'sync_failed' | 'cancelled' | 'rejected'} EventStatus
 */

/**
 * @typedef {'action_required' | 'fyi'} EventImportance
 */

/**
 * @typedef {Object} CalendarEvent
 * @property {string} id - UUID
 * @property {string} user_id - UUID
 * @property {string} title
 * @property {string} [start_datetime]
 * @property {string} [end_datetime]
 * @property {boolean} all_day
 * @property {string} [location]
 * @property {string} [description]
 * @property {string} [source_attribution]
 * @property {EventImportance} importance
 * @property {EventStatus} status
 * @property {string} [google_calendar_event_id]
 * @property {string} [synced_at]
 * @property {string} created_at
 * @property {string} updated_at
 */

/**
 * @typedef {Object} SupabaseServiceResult
 * @template T
 * @property {T} data
 * @property {number | null} [count]
 * @property {import('./errors.js').SupabaseError | null} error
 */

// ============================================================================
// Attachment Types
// ============================================================================

/**
 * @typedef {Object} Attachment
 * @property {string} id - UUID
 * @property {string} user_id - UUID
 * @property {string} email_id - UUID
 * @property {string} [gmail_attachment_id]
 * @property {string} filename
 * @property {string} mime_type
 * @property {number} size_bytes
 * @property {string} [storage_path]
 * @property {string} [content_hash]
 * @property {string} created_at
 */

// ============================================================================
// Event Source Types
// ============================================================================

/**
 * @typedef {'new_invitation' | 'update' | 'cancellation' | 'reminder' | 'unknown'} SourceType
 */

/**
 * @typedef {Object} ExtractedData
 * @property {string} [title]
 * @property {string} [start_datetime]
 * @property {string} [end_datetime]
 * @property {string} [location]
 * @property {string} [description]
 * @property {string} [source_quote]
 */

/**
 * @typedef {'email' | 'google_calendar' | 'google_photos'} SourceOrigin
 */

/**
 * @typedef {Object} EventSource
 * @property {string} id - UUID
 * @property {string} event_id - UUID
 * @property {string} [email_id] - UUID (required for email sources)
 * @property {SourceOrigin} source_origin - Source type: email, google_calendar, or google_photos
 * @property {SourceType} source_type
 * @property {ExtractedData} [extracted_data]
 * @property {Object} [event_snapshot_before]
 * @property {boolean} is_undone
 * @property {string} created_at
 * @property {Email} [emails] - Joined email data
 */

// ============================================================================
// Sender Rule Types
// ============================================================================

/**
 * @typedef {'auto_approve' | 'ignore'} SenderRuleAction
 */

/**
 * @typedef {Object} SenderRule
 * @property {string} id - UUID
 * @property {string} user_id - UUID
 * @property {string | null} sender_domain
 * @property {string | null} sender_email
 * @property {SenderRuleAction} action
 * @property {string} created_at
 * @property {string} updated_at
 */

// ============================================================================
// Calendar Settings Types
// ============================================================================

/**
 * @typedef {Object} CalendarSettings
 * @property {string} user_id - UUID
 * @property {string | null} target_calendar_id
 * @property {string | null} default_invitees
 * @property {string} updated_at
 */

// ============================================================================
// Job Types
// ============================================================================

/**
 * @typedef {'email_fetch' | 'email_process' | 'calendar_sync'} JobType
 */

/**
 * @typedef {'pending' | 'processing' | 'completed' | 'failed' | 'dead'} JobStatus
 */

/**
 * @typedef {Object} Job
 * @property {string} id - UUID
 * @property {string} user_id - UUID
 * @property {JobType} job_type
 * @property {Object} payload
 * @property {JobStatus} status
 * @property {number} priority
 * @property {number} attempts
 * @property {number} max_attempts
 * @property {string | null} last_error
 * @property {string} [scheduled_at]
 * @property {string} [started_at]
 * @property {string} [completed_at]
 * @property {string} created_at
 */

export {};
