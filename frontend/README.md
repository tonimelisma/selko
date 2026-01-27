# Selko Web Frontend

SvelteKit web application for Selko.

## Architecture

**Direct Supabase Access** - The app queries Supabase directly for all data operations using the JavaScript Supabase SDK. The Python API is only used for server-side operations.

```
Web Frontend
    │
    ├─── Data queries ──→ Supabase (direct)
    │    - List emails, events, integrations
    │    - Update event status
    │    - Download attachments
    │
    └─── Server-side ops ──→ Python API
         - OAuth callback handling
         - Email sync triggers
         - LLM processing triggers
         - Calendar sync triggers
```

## Tech Stack

- **Framework**: SvelteKit
- **Supabase**: `@supabase/supabase-js`
- **CSS**: Tailwind CSS
- **Testing**: Vitest (unit), Playwright (e2e)

## Data Access

All data queries use the Supabase JavaScript SDK directly. See `docs/supabase-frontend-queries.md` for canonical query patterns.

```javascript
// Example: List emails
import { supabase } from '$lib/supabase';

const { data: emails, error } = await supabase
  .from('emails')
  .select('*')
  .eq('is_spam', false)
  .eq('is_trash', false)
  .order('date_sent', { ascending: false })
  .limit(20);
```

## Project Structure

```
src/
├── app.html              # HTML template
├── routes/               # SvelteKit routes
│   ├── +layout.svelte   # Root layout
│   └── +page.svelte     # Home page
├── lib/
│   ├── supabase.js      # Supabase client
│   ├── stores.js        # Svelte stores
│   ├── types.js         # Type definitions
│   ├── errors.js        # Error handling
│   └── services/        # Data services
│       ├── emails.js    # Email queries
│       ├── events.js    # Event queries
│       └── backend.js   # Python API client
└── components/           # Reusable components
```

## Development

```bash
# Install dependencies
npm install

# Start dev server
npm run dev

# Run tests (outputs JSON for pre-commit hook)
npm run test:unit -- --reporter=json --outputFile=test-results.json

# Build for production
npm run build
```

## Configuration

Create `.env` file:

```bash
PUBLIC_SUPABASE_URL=http://localhost:54321
PUBLIC_SUPABASE_PUBLISHABLE_KEY=your-publishable-key
PUBLIC_BACKEND_URL=http://localhost:8000
```

## API Services

The `src/lib/services/` directory contains:

| File | Purpose |
|------|---------|
| `emails.js` | Email queries via Supabase |
| `events.js` | Event queries via Supabase |
| `integrations.js` | Integration queries via Supabase |
| `backend.js` | Python API client (server-side ops only) |

The `backend.js` client is **only** for operations requiring server-side secrets:
- `triggerEmailSync()` - POST /emails/sync
- `processEmail(id)` - POST /emails/{id}/process
- `syncEventToCalendar(id)` - POST /events/{id}/sync
- `listCalendars()` - GET /calendars
