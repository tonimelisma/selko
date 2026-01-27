# LLM Evaluation Test Suite

Manual evaluation framework for testing LLM (Gemini) email processing quality.

## Overview

This directory contains ~50 test email fixtures designed to evaluate the LLM's ability to:
- Extract calendar events from various email types
- Parse dates/times correctly (relative dates, timezones, all-day events)
- Handle attachments (text files, ICS calendar files, agendas)
- Process multi-email threads (updates, cancellations, reminders)
- Correctly identify emails with no extractable events

## Directory Structure

```
eval/
├── fixtures/
│   ├── emails/              # Email fixtures organized by category
│   │   ├── invitations/     # Birthday, wedding, party invitations (10)
│   │   ├── appointments/    # Medical, service, professional (8)
│   │   ├── meetings/        # Business, 1:1, team meetings (8)
│   │   ├── travel/          # Flights, hotels, car rentals (6)
│   │   ├── conferences/     # Conferences, webinars (5)
│   │   ├── school/          # School events, sports (5)
│   │   ├── recurring/       # Weekly/monthly recurring (4)
│   │   └── no_events/       # Newsletters, receipts, etc. (10)
│   ├── attachments/         # Text attachment fixtures
│   └── threads/             # Multi-email thread scenarios (4)
├── results/                 # Cached evaluation results (gitignored)
├── run_eval.py              # Evaluation runner CLI
├── eval_config.py           # Configuration
└── conftest.py              # Pytest fixtures
```

## Running Evaluations

### Prerequisites

```bash
# Ensure GEMINI_API_KEY is set
export GEMINI_API_KEY="your-api-key"
```

### Run All Evaluations

```bash
# Run all fixtures against real LLM (costs $$$)
uv run python -m backend.tests.eval.run_eval --all

# Run specific category
uv run python -m backend.tests.eval.run_eval --category invitations

# Run single fixture
uv run python -m backend.tests.eval.run_eval --fixture invitations/birthday_party_01

# Run thread scenarios only
uv run python -m backend.tests.eval.run_eval --threads
```

### Using Cached Results

```bash
# Use cached results if available (skip LLM calls)
uv run python -m backend.tests.eval.run_eval --all --use-cache

# Force re-run even if cached
uv run python -m backend.tests.eval.run_eval --all --no-cache

# Clear all cached results
uv run python -m backend.tests.eval.run_eval --clear-cache
```

### Viewing Results

```bash
# Show summary report
uv run python -m backend.tests.eval.run_eval --report

# Show detailed results for specific fixture
uv run python -m backend.tests.eval.run_eval --show invitations/birthday_party_01

# Export results to CSV
uv run python -m backend.tests.eval.run_eval --export results.csv
```

### Rating Results

After running evaluations, you can manually rate results:

```bash
# Interactive rating mode
uv run python -m backend.tests.eval.run_eval --rate

# Rate specific fixture
uv run python -m backend.tests.eval.run_eval --rate invitations/birthday_party_01
```

Rating scale:
- **5 - Perfect**: Exact match on all fields
- **4 - Excellent**: Minor differences (e.g., slight description variation)
- **3 - Good**: Correct event detection, some field issues
- **2 - Partial**: Missed events or significant extraction errors
- **1 - Failed**: Wrong extraction or false positive/negative

## Fixture Format

### Email Fixture (JSON)

```json
{
  "name": "birthday_party_01",
  "category": "invitations",
  "description": "Child's birthday party invitation with time and location",
  "difficulty": "easy",
  "tags": ["birthday", "kids", "time-parsing"],
  "input": {
    "gmail_id": "eval-inv-001",
    "thread_id": "thread-001",
    "subject": "You're invited to Jake's 7th Birthday!",
    "from_email": "sarah@example.com",
    "from_name": "Sarah Johnson",
    "to_emails": ["you@example.com"],
    "date_sent": "2026-01-20T10:00:00Z",
    "snippet": "Join us to celebrate...",
    "body_text": "Full email body...",
    "attachments": []
  },
  "expected": {
    "events_found": true,
    "event_count": 1,
    "events": [
      {
        "title": "Jake's 7th Birthday Party",
        "start_datetime": "2026-02-15T14:00:00",
        "end_datetime": "2026-02-15T17:00:00",
        "location": "123 Park Lane, Springfield",
        "description": "Birthday party for Jake",
        "is_all_day": false,
        "confidence_min": 0.8
      }
    ]
  },
  "notes": "Tests basic birthday invitation parsing with explicit date/time"
}
```

### Thread Scenario (JSON)

```json
{
  "name": "meeting_update_cancel",
  "description": "Meeting scheduled, then rescheduled, then cancelled",
  "emails": [
    { "fixture": "thread_email_1.json", "expected_action": "create" },
    { "fixture": "thread_email_2.json", "expected_action": "update" },
    { "fixture": "thread_email_3.json", "expected_action": "cancel" }
  ],
  "expected_final_state": {
    "event_count": 1,
    "event_status": "cancelled"
  }
}
```

## Categories Explained

### Invitations (10 fixtures)
- Birthday parties (kids, adults)
- Wedding invitations
- Baby shower
- Graduation party
- Housewarming
- Holiday party
- Retirement party

### Appointments (8 fixtures)
- Doctor appointment
- Dentist appointment
- Car service
- Hair salon
- Lawyer consultation
- Accountant meeting
- Vet appointment
- Home repair service

### Meetings (8 fixtures)
- 1:1 meeting
- Team standup
- Board meeting
- Client call
- Interview
- All-hands meeting
- Project kickoff
- Performance review

### Travel (6 fixtures)
- Flight confirmation
- Hotel reservation
- Car rental
- Train booking
- Airport transfer
- Travel itinerary

### Conferences (5 fixtures)
- Multi-day conference
- Online webinar
- Workshop registration
- Training session
- Virtual summit

### School (5 fixtures)
- Parent-teacher conference
- School play
- Sports game
- Field trip
- Graduation ceremony

### Recurring (4 fixtures)
- Weekly team meeting
- Monthly book club
- Bi-weekly 1:1
- Quarterly review

### No Events (10 fixtures)
- Newsletter
- Order receipt
- Shipping notification
- Marketing email
- Social media notification
- Password reset
- Account statement
- Terms of service update
- Survey request
- Promotional offer

## Attachment Types

Text-based attachments supported:
- `.txt` - Plain text agendas, meeting notes
- `.ics` - iCalendar files
- `.csv` - Schedule spreadsheets
- `.md` - Markdown documents

## Results Cache

Results are cached in `results/` directory as JSON files:

```json
{
  "fixture_name": "birthday_party_01",
  "run_at": "2026-01-27T10:30:00Z",
  "model": "gemini-3-flash-preview",
  "duration_ms": 1234,
  "actual": {
    "events_found": true,
    "events": [...]
  },
  "expected": {
    "events_found": true,
    "events": [...]
  },
  "auto_score": {
    "events_found_match": true,
    "event_count_match": true,
    "field_scores": {...}
  },
  "manual_rating": null,
  "manual_notes": null
}
```

## Cost Estimation

Running full eval suite (~50 fixtures):
- Estimated tokens: ~100K input, ~10K output
- Estimated cost: ~$0.10-0.20 per full run
- Use `--use-cache` to avoid re-running unchanged fixtures

## Adding New Fixtures

1. Create JSON file in appropriate category directory
2. Follow the fixture format schema
3. Add meaningful tags and difficulty level
4. Include notes explaining what the fixture tests
5. Run the fixture to verify it works: `uv run python -m backend.tests.eval.run_eval --fixture <name>`
