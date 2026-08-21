/**
 * @typedef {Object} User
 * @property {string} id - UUID
 * @property {string} email
 * @property {string} [display_name]
 * @property {string} created_at
 * @property {string} updated_at
 */

/**
 * @typedef {'gmail' | 'outlook' | 'google_photos' | 'google_calendar'} IntegrationProvider
 */

/**
 * @typedef {'active' | 'expired' | 'revoked' | 'error'} IntegrationStatus
 */

/**
 * @typedef {'pending' | 'processing' | 'waiting' | 'completed' | 'completed_with_errors' | 'failed' | 'superseded'} IntegrationRecoveryStatus
 */

/**
 * @typedef {Object} IntegrationRecovery
 * @property {string} id - UUID
 * @property {string} integration_id - UUID
 * @property {string} user_id - UUID
 * @property {IntegrationProvider} provider
 * @property {IntegrationRecoveryStatus} status
 * @property {number} [discovered_count]
 * @property {number} [completed_count]
 * @property {number} [remaining_count]
 * @property {number} [withdrawn_count] - 7a: cancelled/rejected mid-recovery (terminal-not-errored)
 * @property {string} [error_detail]
 * @property {string} requested_at
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
 * @typedef {'no_event' | 'event_matched' | 'event_created' | 'event_updated' | 'event_created_and_updated' | 'event_cancelled' | 'cancellation_unmatched' | 'cancellation_ambiguous' | 'calendar_invite'} EmailProcessingOutcome
 */

/**
 * @typedef {Object} Email
 * @property {string} id - UUID
 * @property {string} user_id - UUID
 * @property {string} [integration_id] - UUID
 * @property {string} email_provider
 * @property {string} provider_message_id
 * @property {string} [thread_id]
 * @property {string} [subject]
 * @property {string} [from_email]
 * @property {string} [from_name]
 * @property {string[]} [to_emails]
 * @property {string} [date_sent]
 * @property {string} [snippet]
 * @property {string[]} provider_labels
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
 * @property {EmailProcessingOutcome} [processing_outcome]
 * @property {string} [processing_explanation]
 * @property {string} [processing_error]
 * @property {string} created_at
 */

/**
 * @typedef {'pending_review' | 'approved' | 'syncing' | 'synced' | 'sync_failed' | 'cancel_queued' | 'cancelled' | 'rejected'} EventStatus
 */

/**
 * @typedef {'pending_review' | 'active' | 'rejected' | 'cancelled'} EventReviewStatus
 */

/**
 * @typedef {'pending' | 'applied' | 'rejected' | 'superseded' | 'closed_legacy'} EventChangeProposalStatus
 */

/**
 * @typedef {'material_update' | 'cancellation'} EventChangeProposalKind
 */

/**
 * @typedef {Object} EventChangeProposal
 * @property {string} id
 * @property {string} event_id
 * @property {string} user_id
 * @property {string} source_id
 * @property {EventChangeProposalKind} kind
 * @property {EventChangeProposalStatus} status
 * @property {Object} change_set
 * @property {Object} event_snapshot_before
 * @property {string|null} [resolution_reason]
 * @property {string} created_at
 * @property {string|null} [resolved_at]
 * @property {string} updated_at
 */

/**
 * @typedef {'upsert' | 'cancel'} CalendarWorkAction
 */

/**
 * @typedef {'pending' | 'processing' | 'succeeded' | 'failed' | 'blocked' | 'superseded'} CalendarWorkStatus
 */

/**
 * @typedef {Object} CalendarWorkItem
 * @property {string} id
 * @property {string} event_id
 * @property {string} user_id
 * @property {CalendarWorkAction} action
 * @property {number} generation
 * @property {CalendarWorkStatus} status
 * @property {Object|null} [desired_event]
 * @property {string|null} [provider_event_id]
 * @property {string|null} [expected_provider_revision]
 * @property {boolean} force_overwrite
 * @property {number} attempts
 * @property {number} max_attempts
 * @property {string|null} [next_retry_at]
 * @property {string|null} [failure_code]
 * @property {string|null} [failure_detail]
 * @property {string} created_at
 * @property {string} updated_at
 * @property {string|null} [completed_at]
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
 * @property {EventStatus} status - Derived from review_status and calendar_work_items; not stored on events
 * @property {string} [google_calendar_event_id]
 * @property {string} [synced_at]
 * @property {EventReviewStatus} review_status
 * @property {string} created_at
 * @property {string} updated_at
 * @property {EventSource[]} [event_sources]
 * @property {EventChangeProposal[]} [event_change_proposals]
 * @property {CalendarWorkItem[]} [calendar_work_items]
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
 * @property {string} [provider_attachment_id]
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
