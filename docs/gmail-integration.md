# **Comprehensive Architectural Specification: Real-Time Gmail Synchronization and Data Extraction Backend**

## **1\. Executive Summary**

The integration of backend systems with Gmail for the purpose of real-time monitoring, classification, and data extraction represents a complex engineering challenge that intersects distributed messaging, secure authentication, and granular API resource management. The requirement to monitor "authorized users' gmail accounts" implies a multi-tenant architecture where the backend must maintain persistent, secure connections to disparate mailboxes, responding to events such as message arrival, status changes (read/unread), and folder routing with minimal latency. While traditional polling models provided the foundation for early email integrations, modern requirements for "near real-time" performance necessitate an event-driven architecture utilizing Google Cloud Pub/Sub in conjunction with the Gmail REST API.  
This report provides an exhaustive technical analysis and implementation guide for building a backend capability that satisfies these requirements. It details the transition from polling to push notifications, the nuanced handling of Gmail's "History" system to track state changes, the taxonomy of System Labels for classification (Spam, Promotions, Social), and the recursive parsing logic required to extract binary attachments from MIME-encoded payloads. Furthermore, it addresses the critical operational constraints imposed by Google’s security policies regarding "Restricted Scopes," providing a roadmap for OAuth 2.0 compliance and offline access management.  
The recommended architecture is a **Hybrid Push-Sync Model**. In this paradigm, Google Cloud Pub/Sub serves as the trigger mechanism, notifying the backend of state changes via a webhook or pull subscription. Upon receipt of a notification, the backend utilizes the Gmail API’s history.list method to retrieve specific deltas—identifying not just that a change occurred, but specifically *what* changed (e.g., a label removal indicating a message was marked as read). This approach minimizes API quota consumption while maximizing responsiveness. The report also details a fallback polling strategy to ensure system resilience in the event of notification failures.

## **2\. Architectural Paradigms: Push vs. Polling**

Designing a system to read "all the latest emails" requires a fundamental choice between polling (pulling data at intervals) and push notifications (receiving data upon events). The user's request prioritizes a "push-model" but acknowledges "polling" as an alternative. A nuanced understanding of the trade-offs is essential for a robust implementation.

### **2.1 The Polling Model (Alternative Architecture)**

The polling model is the simplest to implement but the least efficient for real-time requirements. In this architecture, the backend periodically executes a users.messages.list request for every authorized user to check for new items.  
**Mechanics of Polling:**  
To implement polling, the backend must maintain a scheduler (e.g., Celery beat, cron) that triggers a job for each user. The job executes a list request, typically filtering by labelIds= and comparing the returned message IDs against a local database of known messages. To detect changes in state (like a message being marked read), the system would need to re-fetch the metadata of known messages and compare the labelIds list (checking for the absence of UNREAD).  
**Limitations and Costs:**

* **Latency:** The "real-time" nature is strictly bound by the polling interval. A 5-minute interval introduces up to 5 minutes of latency. Reducing this interval linearly increases API calls.  
* **Quota Consumption:** The Gmail API enforces daily usage limits (Compute Units). A messages.list call costs 5 quota units.1 Polling a single user every minute consumes ![][image1] units per day. With a standard free tier quota (often 1,000,000,000 units but subject to user rate limits), scaling this to thousands of users creates a bottleneck.  
* **Compute Waste:** The vast majority of polling calls return no new data (empty diffs), resulting in wasted CPU cycles and network bandwidth.

While polling is suboptimal for the primary ingestion channel, it remains a critical **fallback mechanism**. If the push notification pipeline fails (e.g., webhook downtime, subscription expiry), a low-frequency poll (e.g., once every 24 hours) acts as a sanity check to ensure consistency.

### **2.2 The Push Model (Google Cloud Pub/Sub)**

The preferred architecture utilizes the users.watch API endpoint combined with Google Cloud Pub/Sub. This creates an event-driven pipeline where Gmail acts as the publisher and the backend acts as the subscriber.  
**Workflow Overview:**

1. **Registration:** The backend calls users.watch on the user's mailbox, specifying a Cloud Pub/Sub topic.2  
2. **Event Generation:** When the user receives an email or modifies a label, Gmail publishes a lightweight notification to the topic.  
3. **Delivery:** Cloud Pub/Sub delivers this message to the backend (via Webhook or Pull).  
4. **Synchronization:** The backend uses the notification to trigger a specific sync operation.

**Advantages:**

* **Near Real-Time Latency:** Notifications typically arrive within seconds of the event.  
* **Efficiency:** API calls are made only when actual changes occur. The history.list call used to fetch changes consumes only 2 quota units, less than half the cost of a polling list call.1  
* **Scalability:** Google Cloud Pub/Sub handles the queuing and delivery logic, allowing the backend to decouple ingestion from processing.

**Comparison Table: Polling vs. Push**

| Feature | Polling | Push (Pub/Sub) |
| :---- | :---- | :---- |
| **Latency** | High (Dependent on interval) | Low (Sub-second to seconds) |
| **Complexity** | Low | High (Requires Infra setup) |
| **Quota Cost** | High (Linear with frequency) | Low (Linear with event volume) |
| **State Tracking** | Difficult (Requires deep diffing) | Native (Via History API) |
| **Empty Cycles** | High | Zero |

## **3\. Authentication and Security Compliance**

Connecting to authorized users' Gmail accounts requires navigating Google’s rigorous OAuth 2.0 infrastructure. Since the backend must operate "offline" (without the user present) and access sensitive data (email content), the security configuration is non-trivial.

### **3.1 OAuth 2.0 Web Server Flow for Offline Access**

The backend must utilize the **Authorization Code Flow** to obtain credentials. A critical requirement for a backend service is the **Refresh Token**. Access tokens issued by Google are short-lived, typically expiring after one hour.3 Without a refresh token, the backend would lose access after 60 minutes, requiring the user to re-authenticate—a scenario compatible with the requirements.  
**The Authorization Sequence:**

1. **Consent Request:** The backend constructs an authorization URL redirecting the user to Google. This URL must include two specific query parameters:  
   * access\_type='offline': This signals Google to provision a refresh token.4  
   * prompt='consent': This forces the consent screen to appear. This is mandatory to ensure a refresh token is returned. If a user has previously granted access and the prompt is not forced, Google may return only an access token, leaving the backend without a mechanism for long-term access.5  
2. **Code Exchange:** Upon user approval, Google redirects to the backend's callback URL with a temporary authorization code. The backend exchanges this code for a credential object containing:  
   * access\_token: Used for API calls.  
   * refresh\_token: Stored permanently in the database (encrypted at rest).  
   * token\_uri: The endpoint to refresh credentials.  
   * client\_id / client\_secret: Application credentials.  
3. **Token Refreshing:** The standard Python library google-auth handles the refresh lifecycle automatically. When an API call is attempted with an expired access token, the library uses the stored refresh token to fetch a new one transparently, provided the Credentials object is correctly initialized with the refresh token.6

### **3.2 Scope Selection and Verification**

The user requires reading content, seeing attachments, and tracking read/unread status. These actions dictate the specific OAuth scopes required.  
**Required Scopes:**

* **https://www.googleapis.com/auth/gmail.readonly**: This scope allows the backend to read all resources and their metadata. It is required to "read all the latest emails" and "see emails' attachments".8  
* **https://www.googleapis.com/auth/gmail.labels**: This scope allows listing and reading labels, which is necessary to classify emails (Spam, Promotions) and map Label IDs to human-readable names.9  
* **https://www.googleapis.com/auth/gmail.modify**: This scope allows the backend to *change* labels. While the prompt emphasizes *reading* data, it asks to "see when emails are directly marked read." To reliably track this and potentially sync state back (if required in future), modify is often safer, but readonly is sufficient strictly for *monitoring*. However, if the user intends to download attachments and then *remove* them from the server or mark them as processed, modify is essential.

**Restricted Scope Implications:** Both gmail.readonly and gmail.modify are classified by Google as **Restricted Scopes**.8 This classification triggers a mandatory **Security Assessment** for any application that is public-facing (i.e., verifying the app for general use rather than internal testing).

* **Testing Mode:** For development or personal use (limited to 100 specific test users), the app can remain unverified. Users will see a "Google hasn't verified this app" warning screen.  
* **Production Verification:** To launch publicly, the backend owner must undergo a CAS (Cloud Application Security) assessment conducted by a third-party lab. This process typically costs between $15,000 and $75,000 annually and takes several weeks.11

### **3.3 Service Accounts vs. User Credentials**

It is a common architectural error to attempt using **Service Accounts** (JSON key files) to access standard Gmail accounts (@gmail.com). Service accounts act as their own identity. They cannot access a user's Gmail data unless **Domain-Wide Delegation** is configured.3 Domain-Wide Delegation is only available for Google Workspace (enterprise) domains and must be enabled by a super administrator.

* **Conclusion:** For a generic application connecting to arbitrary "authorized users" (including personal accounts), Service Accounts cannot be used. The architecture must rely on standard OAuth 2.0 User Credentials managed via the flow described in Section 3.1.

## **4\. Implementing the Real-Time Push Pipeline**

To satisfy the "near real-time push-model" requirement, the implementation must orchestrate the interaction between the Gmail API, Cloud Pub/Sub, and the backend receiver.

### **4.1 Cloud Pub/Sub Configuration**

The Pub/Sub system acts as the intermediary buffer. This ensures that if the backend is temporarily overwhelmed or offline, notifications are queued rather than lost.  
**Step 1: Topic Creation** A topic must be created in the Google Cloud Console (e.g., projects/my-app/topics/gmail-inbox-watch).2  
**Step 2: Granting Publish Privileges (Critical Step)**  
The Gmail API infrastructure itself publishes messages to this topic. For this to succeed, the topic's access control list (ACL) must explicitly allow the Gmail service account to publish.

* **Principal:** gmail-api-push@system.gserviceaccount.com  
* **Role:** Pub/Sub Publisher Without this specific IAM binding, calls to users.watch will fail with a 403 Forbidden error.2

**Step 3: Subscription Setup**  
A subscription connects the topic to the backend. Two modes are available:

* **Push Subscription:** Pub/Sub sends an HTTPS POST request to a public endpoint on the backend (e.g., https://api.myapp.com/webhooks/gmail). This is the most direct mapping to the user's "push-model" request.13  
* **Pull Subscription:** The backend runs a background worker (e.g., a Python script using google-cloud-pubsub) that maintains a persistent connection to Google Cloud and pulls messages as they arrive.  
  * *Recommendation:* Pull subscriptions are generally more robust for high-volume backends as they allow the application to control the rate of ingestion (flow control) and avoid being DDoS'd by a sudden influx of email notifications. However, Push subscriptions are easier to integrate into serverless architectures (like AWS Lambda or Google Cloud Functions).

### **4.2 The users.watch Lifecycle**

The watch command is the trigger that tells Gmail: "Start sending events for *this* user to *this* topic."  
**Request Anatomy:**  
The request is a POST to https://www.googleapis.com/gmail/v1/users/me/watch.  
Body Parameters:

* topicName: The full resource name of the Pub/Sub topic.  
* labelIds: (Optional) A list of labels to watch. To monitor *everything* (spam, inbox, trash, custom folders), this list should be omitted or explicitly set to include all relevant system labels.2  
* labelFilterBehavior: Set to INCLUDE or EXCLUDE.

**The Expiration Constraint:** A critical detail often missed is that a Gmail watch subscription **expires after 7 days**.2 There is no automatic renewal.

* **Implication:** The backend must implement a scheduler (cron job) that runs daily (or every few days) and re-issues the users.watch call for every active user in the system. Failing to do so will cause notifications to silently cease after one week. The response to the watch call includes an expiration timestamp (epoch milliseconds) which can be stored to optimize this renewal schedule.15

### **4.3 Notification Payload Analysis**

The payload received from Pub/Sub is not the email itself. It is a signal notification designed to be privacy-safe and lightweight.  
**Decoded Structure:**  
The Pub/Sub message body contains a data field which is Base64-encoded. Upon decoding, the JSON structure is:

JSON

{  
  "emailAddress": "user@example.com",  
  "historyId": 123456789  
}

2  
**Missing Information & Strategy:**  
The notification does *not* contain the subject, sender, body, or attachment info. It effectively says: "Something changed in the mailbox of user@example.com, and the new history state ID is 123456789."  
This necessitates the **Sync Phase**, where the backend uses this historyId to fetch the actual data.

## **5\. Synchronization Mechanics: The History API**

The core logic for "reading latest emails," "tracking folder routing," and "seeing read/unread status" lies in the interpretation of the Gmail History API. This API is efficient because it returns *deltas* (changes) rather than the full mailbox state.

### **5.1 History.list and the Sync Token**

To use the History API effectively, the backend must persist a last\_synced\_history\_id for each user.

* **Initial State:** When a user first connects, the backend performs a full list or watch call, which returns the current historyId. This is stored as the cursor.  
* **Event Processing:** When a push notification arrives with a new historyId (let's call it ![][image2]), the backend calls users.history.list requesting all changes starting from the stored cursor (![][image3]).17

**API Call:**  
service.users().history().list(userId='me', startHistoryId=last\_synced\_history\_id).execute()

### **5.2 Interpreting State Changes**

The history.list response contains a list of history records. Each record contains lists of events that map directly to the user's requirements.18

#### **5.2.1 Reading Latest Emails**

New emails appear in the messagesAdded list within the history record.

* **Data Available:** The record provides the messageId and threadId.  
* **Action:** The backend must iterate through messagesAdded, extract the IDs, and queue a users.messages.get call to download the content and attachments.

#### **5.2.2 Tracking "Marked Read"**

The user explicitly wants to "see when emails are directly marked read." In Gmail's architecture, "Read" is not a label; "Unread" is. Therefore, marking an email as read is equivalent to **removing** the UNREAD label.

* **Detection Logic:** The backend must verify if the history record contains a labelsRemoved event. Inside this event, check if UNREAD is present in the labelIds list.  
* **Insight:** If the UNREAD label is removed, the email has been marked read. Conversely, if UNREAD is found in labelsAdded, the email was marked unread.

#### **5.2.3 Tracking "Routed to Different Folders"**

The user wants to see emails "routed to different folders." Gmail uses labels, not folders, so a "move" operation is technically an atomic addition of a new label and removal of the old label (usually INBOX).

* **Detection Logic:**  
  * **Arrival in Folder:** Look for labelsAdded events. If a message receives the label Work, it has been routed to that folder.  
  * **Archival:** If a message appears in labelsRemoved with the label INBOX, it has been archived (removed from the inbox).  
  * **Trash/Spam:** Movement to Trash or Spam is indicated by labelsAdded events containing TRASH or SPAM.

### **5.3 Handling Consistency Gaps (404 Logic)**

A crucial edge case in the History API is the validity window of historyId. History records are typically available for roughly 30 days. However, if a historyId is too old, or if the backend sends an invalid ID, the API returns a **404 Not Found** error.17  
**Recovery Strategy (Full Sync):**  
If history.list returns a 404, the historyId chain is broken. The backend must:

1. Log the error.  
2. Perform a **Full Sync**: Call users.messages.list to fetch the latest message IDs.  
3. Compare these IDs against the local database to backfill any missed items.  
4. Update the stored last\_synced\_history\_id to the new value returned by the list operation.

## **6\. Classification and System Labels**

To fulfill the requirement to "classify as promotional, spam, etc.," the backend must leverage Gmail's internal System Labels. Gmail automatically analyzes incoming mail and applies these labels before the backend even sees the message.

### **6.1 Taxonomy of System Labels**

The labelIds field in a Message resource contains both user-created labels (e.g., "Soccer Team") and reserved system labels.19  
**Table: Gmail System Labels and Classification Mapping**

| System Label ID | Classification Meaning |
| :---- | :---- |
| SPAM | **Spam / Junk** |
| TRASH | **Deleted** |
| CATEGORY\_PROMOTIONS | **Promotional / Marketing** (Matches "Promotions" tab) |
| CATEGORY\_SOCIAL | **Social** (Matches "Social" tab) |
| CATEGORY\_UPDATES | **Updates** (Bills, receipts, transactional) |
| CATEGORY\_FORUMS | **Forums** (Mailing lists) |
| CATEGORY\_PERSONAL | **Primary** (Matches "Primary" inbox) |
| IMPORTANT | **Important** (Marked by Gmail's priority AI) |
| STARRED | **Starred/Flagged** by user |

### **6.2 Classification Logic**

When the backend fetches a message (via messages.get), it receives the labelIds list.

* **Spam Detection:** Check if 'SPAM' in message\['labelIds'\]. Note that users.messages.list filters out spam by default; to see these, the parameter includeSpamTrash=True must be set in the API call.  
* **Promotional Detection:** Check if 'CATEGORY\_PROMOTIONS' in message\['labelIds'\].

By mapping these IDs, the backend can immediately tag incoming emails with the correct classification without implementing its own machine learning models.

## **7\. Attachment Extraction and Management**

The requirement to "see emails' attachments and download them" requires navigating the MIME (Multipurpose Internet Mail Extensions) structure of the email.

### **7.1 Recursive MIME Parsing**

The Message resource payload is a tree structure.

* **Simple Email:** payload \-\> body \-\> data.  
* **Email with Attachment:** payload \-\> parts (List).

The backend must recursively traverse the parts list. A part may be a container (e.g., multipart/mixed) which contains other parts. **Identification:** A part represents an attachment if it has a non-empty filename field.21

### **7.2 Retrieval Strategies: Inline vs. Reference**

Gmail optimizes payload size by handling attachments in two ways 22:

1. **Small Attachments (Inline):**  
   For small files, the binary data may be included directly in the body.data field of the message part.  
2. **Large Attachments (Reference):**  
   For larger files, body.data will be null. Instead, the part will contain a body.attachmentId.

**Download Protocol:**  
To "download" the attachment, the backend logic must be:

1. Check part\['body'\].  
2. If data exists: Decode it directly.  
3. If attachmentId exists: Call the users.messages.attachments.get endpoint using the messageId and attachmentId. This returns a JSON object containing the data field.

### **7.3 Base64URL Decoding**

A critical technical detail is the encoding format. Gmail uses **Base64URL** strings (RFC 4648), not standard Base64.

* **Standard Base64:** Uses \+ and /.  
* **Base64URL:** Uses \- and \_ to be safe for URLs.  
* **Padding:** Base64 strings must be a multiple of 4 characters. Gmail API responses may omit the padding characters (=). **Python Implementation:** The backend must use base64.urlsafe\_b64decode(). It requires robust error handling to add padding if necessary before decoding.24

## **8\. Python Implementation Strategy**

The following section translates the architectural concepts into a concrete implementation strategy using the standard Google Python client libraries.

### **8.1 Library Requirements**

The standard libraries provided by Google support all necessary operations.

Bash

pip install \--upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib

### **8.2 Operational Logic (Pseudocode)**

The following logic flow synthesizes the Push, Sync, and Download requirements.

Python

import base64  
from googleapiclient.discovery import build

def handle\_push\_notification(user\_id, incoming\_history\_id, stored\_history\_id):  
    service \= get\_authenticated\_service(user\_id)  
      
    \# 1\. Sync Phase: Get Deltas  
    try:  
        response \= service.users().history().list(  
            userId='me',   
            startHistoryId=stored\_history\_id  
        ).execute()  
    except HttpError as e:  
        if e.resp.status \== 404:  
            \# Handle History Gap  
            return perform\_full\_sync(service)  
      
    \# 2\. Iterate Changes  
    if 'history' in response:  
        for record in response\['history'\]:  
              
            \# A. Handle New Messages  
            if 'messagesAdded' in record:  
                for msg in record\['messagesAdded'\]:  
                    process\_message(service, msg\['message'\]\['id'\])  
              
            \# B. Handle State Changes (Read/Routing)  
            if 'labelsRemoved' in record:  
                for label\_rec in record:  
                    if 'UNREAD' in label\_rec\['labelIds'\]:  
                        print(f"Msg {label\_rec\['message'\]\['id'\]} marked READ")  
                          
            if 'labelsAdded' in record:  
                 for label\_rec in record\['labelsAdded'\]:  
                     print(f"Msg routed to folder: {label\_rec\['labelIds'\]}")

def process\_message(service, message\_id):  
    \# Fetch full message details including payload  
    msg \= service.users().messages().get(userId='me', id=message\_id).execute()  
      
    \# 3\. Classification  
    labels \= msg.get('labelIds',)  
    if 'CATEGORY\_PROMOTIONS' in labels:  
        log\_classification("Promotional")  
    elif 'SPAM' in labels:  
        log\_classification("Spam")  
          
    \# 4\. Attachment Downloading  
    process\_parts(service, message\_id, msg\['payload'\])

def process\_parts(service, message\_id, payload):  
    \# Recursive traversal  
    if 'parts' in payload:  
        for part in payload\['parts'\]:  
            process\_parts(service, message\_id, part)  
              
    if payload.get('filename'):  
        \# It is an attachment  
        file\_data \= None  
        if 'data' in payload\['body'\]:  
            file\_data \= base64.urlsafe\_b64decode(payload\['body'\]\['data'\])  
        elif 'attachmentId' in payload\['body'\]:  
            \# Fetch large attachment  
            att \= service.users().messages().attachments().get(  
                userId='me',   
                messageId=message\_id,   
                id=payload\['body'\]\['attachmentId'\]  
            ).execute()  
            file\_data \= base64.urlsafe\_b64decode(att\['data'\])  
              
        save\_file(payload\['filename'\], file\_data)

### **8.3 Error Handling and Exponential Backoff**

Distributed systems often face transient network failures or rate limits (429 Too Many Requests). The implementation must utilize **Exponential Backoff**.

* **Strategy:** If a request fails with a 5xx error or 429, wait 1 second, retry. If fail, wait 2 seconds, retry. Then 4, 8, 16, up to a maximum (e.g., 60 seconds).13  
* **Library Support:** The googleapiclient allows attaching Http objects that can be configured with retry logic, but explicit handling in the application layer is recommended for the watch and history loops.

## **9\. Conclusion**

The construction of a backend that connects to Gmail accounts, ingests emails in real-time, classifies content, and manages attachments requires a sophisticated orchestration of the **Gmail API v1**, **OAuth 2.0**, and **Google Cloud Pub/Sub**.  
By adopting the **Push-Sync architecture**, the system minimizes latency and quota usage compared to polling. The **History API** satisfies the requirements for granular state tracking (read status, folder routing), while the inspection of **System Labels** satisfies the classification requirements. Finally, a recursive traversal of the **MIME payload structure** combined with the specific attachment retrieval endpoint ensures reliable access to binary assets. This architecture provides a scalable, secure, and compliant foundation for advanced email processing applications.

---

## Appendix: Selko-Specific — Calendar Invitation Handling

*(The sections above are general Gmail API research; this appendix documents Selko's actual, current behavior for both Gmail and Outlook.)*

Calendar invitation emails (Google/Outlook meeting requests, updates, RSVPs, cancellations) are never surfaced as Selko suggestions — the user's email client and its calendar already own them. Plain "add to calendar" `.ics` files (RFC 5545 `METHOD:PUBLISH` or no `METHOD`) are not invites and still extract normally.

**Detection is structural, not subject-line based, and happens at ingestion (fetch time) with a process-time backstop:**

* **Outlook:** Graph returns meeting mails as `eventMessage` subtypes. `parse_outlook_message` (`backend/selko/services/outlook.py`) sets `is_calendar_invite` from `@odata.type` containing `eventmessage`.
* **Gmail:** invites carry a `text/calendar` MIME part whose RFC 5545 `METHOD` (`REQUEST`/`REPLY`/`CANCEL`/`COUNTER`/`DECLINECOUNTER`) distinguishes real invite machinery from a shareable calendar file (`PUBLISH`/no `METHOD`). `parse_gmail_message` (`backend/selko/services/emails.py`) resolves the METHOD from the part's `Content-Type` header (`method=REQUEST` parameter) or, failing that, from the inline base64url body (`METHOD:` line). An attachment-only body (no inline data) is left undetermined at ingest time — the process-time backstop below covers it.

**Flagged emails are stored pre-skipped**, via a shared `mark_parsed_as_calendar_invite()` helper (`emails.py`) called from both parse paths: `processing_status='skipped'`, `processing_outcome='calendar_invite'`, with an explanation. Because `save_emails` upserts the parsed dict as-is and `claim_unprocessed_email` only claims `'pending'` rows, these emails are never queued for LLM processing.

**A process-time backstop** in `process_email_for_events` (`events.py`) — using `ics_parser.detect_invite_method()` on the stored `.ics` attachment plus the `is_calendar_invite` column — catches the cases ingest-time detection can't: the `reprocess_email` RPC resetting an invite back to `pending`, a Gmail `.ics` whose METHOD was only readable from the stored attachment, and emails ingested before this feature shipped. It marks the email `skipped` (matching the ingest-time marking) with the same `calendar_invite` outcome, and the LLM gateway is never invoked.

**In History**, invites appear as skipped-with-reason (`history.emailCalendarInvite`) — never as a silent gap — so the row is both the audit trail and the recovery path if detection ever misfires.

#### **Works cited**

1. List Gmail messages \- Google for Developers, accessed January 21, 2026, [https://developers.google.com/workspace/gmail/api/guides/list-messages](https://developers.google.com/workspace/gmail/api/guides/list-messages)  
2. Push Notifications | Gmail | Google for Developers, accessed January 21, 2026, [https://developers.google.com/workspace/gmail/api/guides/push](https://developers.google.com/workspace/gmail/api/guides/push)  
3. Implement server-side authorization | Gmail \- Google for Developers, accessed January 21, 2026, [https://developers.google.com/workspace/gmail/api/auth/web-server](https://developers.google.com/workspace/gmail/api/auth/web-server)  
4. Using OAuth 2.0 for Web Server Applications | Authorization \- Google for Developers, accessed January 21, 2026, [https://developers.google.com/identity/protocols/oauth2/web-server](https://developers.google.com/identity/protocols/oauth2/web-server)  
5. How to get permanent refresh token for personal Gmail API application, accessed January 21, 2026, [https://community.latenode.com/t/how-to-get-permanent-refresh-token-for-personal-gmail-api-application/35300](https://community.latenode.com/t/how-to-get-permanent-refresh-token-for-personal-gmail-api-application/35300)  
6. Python quickstart | Gmail \- Google for Developers, accessed January 21, 2026, [https://developers.google.com/workspace/gmail/api/quickstart/python](https://developers.google.com/workspace/gmail/api/quickstart/python)  
7. Google email help : r/learnpython \- Reddit, accessed January 21, 2026, [https://www.reddit.com/r/learnpython/comments/1nwg3i9/google\_email\_help/](https://www.reddit.com/r/learnpython/comments/1nwg3i9/google_email_help/)  
8. Choose Gmail API scopes \- Google for Developers, accessed January 21, 2026, [https://developers.google.com/workspace/gmail/api/auth/scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)  
9. Method: users.labels.list | Gmail \- Google for Developers, accessed January 21, 2026, [https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.labels/list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.labels/list)  
10. Manage App Data Access \- Google Cloud Platform Console Help, accessed January 21, 2026, [https://support.google.com/cloud/answer/15549135?hl=en](https://support.google.com/cloud/answer/15549135?hl=en)  
11. Google verification and security assessment guide \- Nylas Docs, accessed January 21, 2026, [https://developer.nylas.com/docs/provider-guides/google/google-verification-security-assessment-guide/](https://developer.nylas.com/docs/provider-guides/google/google-verification-security-assessment-guide/)  
12. Receive Gmail Push Notifications Using Google Cloud Pub/Sub | Torq Knowledge Base, accessed January 21, 2026, [https://kb.torq.io/en/articles/9138324-receive-gmail-push-notifications-using-google-cloud-pub-sub](https://kb.torq.io/en/articles/9138324-receive-gmail-push-notifications-using-google-cloud-pub-sub)  
13. Push subscriptions | Pub/Sub \- Google Cloud Documentation, accessed January 21, 2026, [https://docs.cloud.google.com/pubsub/docs/push](https://docs.cloud.google.com/pubsub/docs/push)  
14. Payload unwrapping for Pub/Sub push subscriptions \- Google Cloud Documentation, accessed January 21, 2026, [https://docs.cloud.google.com/pubsub/docs/payload-unwrapping](https://docs.cloud.google.com/pubsub/docs/payload-unwrapping)  
15. Method: users.watch | Gmail \- Google for Developers, accessed January 21, 2026, [https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/watch](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/watch)  
16. Gmail pub/sub API for Python \[closed\] \- Stack Overflow, accessed January 21, 2026, [https://stackoverflow.com/questions/78138998/gmail-pub-sub-api-for-python](https://stackoverflow.com/questions/78138998/gmail-pub-sub-api-for-python)  
17. Synchronizing Clients with Gmail | Google for Developers, accessed January 21, 2026, [https://developers.google.com/workspace/gmail/api/guides/sync](https://developers.google.com/workspace/gmail/api/guides/sync)  
18. Method: users.history.list | Gmail \- Google for Developers, accessed January 21, 2026, [https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list)  
19. Gmail API Overview \- Google for Developers, accessed January 21, 2026, [https://developers.google.com/workspace/gmail/api/guides](https://developers.google.com/workspace/gmail/api/guides)  
20. Manage labels | Gmail \- Google for Developers, accessed January 21, 2026, [https://developers.google.com/workspace/gmail/api/guides/labels](https://developers.google.com/workspace/gmail/api/guides/labels)  
21. Method: users.messages.get | Gmail | Google for Developers, accessed January 21, 2026, [https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get)  
22. Method: users.messages.attachments.get | Gmail \- Google for Developers, accessed January 21, 2026, [https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages.attachments/get](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages.attachments/get)  
23. Uploading Attachments | Gmail \- Google for Developers, accessed January 21, 2026, [https://developers.google.com/workspace/gmail/api/guides/uploads](https://developers.google.com/workspace/gmail/api/guides/uploads)  
24. How to Use Gmail API in Python, accessed January 21, 2026, [https://thepythoncode.com/article/use-gmail-api-in-python](https://thepythoncode.com/article/use-gmail-api-in-python)  
25. How to properly decode the payload of a pubsub message in pyspark / databricks?, accessed January 21, 2026, [https://stackoverflow.com/questions/79620016/how-to-properly-decode-the-payload-of-a-pubsub-message-in-pyspark-databricks](https://stackoverflow.com/questions/79620016/how-to-properly-decode-the-payload-of-a-pubsub-message-in-pyspark-databricks)

[image1]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAKkAAAAXCAYAAABwFW8qAAAE2ElEQVR4Xu2aa6hVRRTHV1aYRaFF+KGHkJBlkZWKRCI3FCKCQq1UwkdeKCNKCyq0QrKHkRFUJgaJWoYYgRJUWFAfohDNysokqA/SAzOlFz0QS9f/rJlz115nZt/Z5557zvkwP/hznP+se2bts2fPa0uUyWQymUwmk8l0B/eytrDGuvJFrE2sJfWI9nE66zvWMdanps7zCOsP1t+sXlPXLiazDpHkuYM1pFgdBDnPtGYbQa6PsRaybmXNZs1yOk/FpfAuyff9SvJ9IU6jvrhdrBOK1TVSYmo8ThKk9Vkhoj0sIGn7ZFdezvq9Xit8zXpPlb9ifaTK7eAF1hpVxsOCvC9QnuUOkphOddLzqfEea6E+FX2P5rjywb7qGuc4f5grn+XK+mFOiamDzvA8ayPrYdaJxeq2cDZJgqcoz/+AnjNM2QNvuDUHEbQ3KeCFcvP8QlLfqU56F+tZ1hWsC1mjSR6qB1kvqbj+eIe1zXhvkVzbDcr7i2R21nzC+leVU2LqoGNeY81E7raGYYI1IoRu8qmm/Dk1xgB4L1szQCtyxfQUyjXkeX5zn53spNutwZxEMgtU4SjJddykvEuc97PyUL5FlcEy53tSYuo8RM13UqxnN1vTMZ31gTUjILEv3b+vIlmbWmIdIeZbWpUr1nVXGy+WwzySZQzoZCcNgQ5XFUzRrxivh+TadrvyFFfGul0z3/lnUlpMgaWsJ0gq17vPKlMA/n6r8WawPjRejItJ2nyNtYdktFrtPE2sI8T8EAPNNQba/9+aJJslD2K6pZNiTf2oNZsEozSu7VJXxoYb5SvrEcLNzsdSKSWmwH3UOB0gECNGKhim/VoFN73KZsYvvm1Hw03/R5VDMSDmxxhIriG+IGnfLk8w/endamonxW771Ygwim0gGUzWkSxznqv9VTWq/F5lYP+C78LO3LPCeZcpD2C2go+ThZSYfql64wFu/sckRzJVuJ6krZ+M/77zPbGcYn4ZzeZqwROPtrHx0+Ca7jEe4lI66WDzDFX/vWJgEPHTvOd2ku+/3PhYx8KfSmkxBUJnU/9R9QvpZX3DettW9MMokrYwUmjedP5EV451xphfRrO5akaQtDvUVlBxBvB0SydFHjut2QR7Wa9bk/rWm9hbaOY6H+valJgCMA8HvCo3Hjfdr+sWkXSwKqAtexzhjzZwZAL+dGULvH3WLGGguQKc5dlc9EOG79fC0YrP07cdYxrr6QrCOXcVkMdT1qzIGyT7GM337hMPLdoo27mnxBSAeX/ACwYHwBsH+8Pj5tvztDLQ1rfGs0dOuKBQTvDGWzNCK3IFoU0SZp8YeNCQZ6dH0htJ8lhsKxyYVXEkWcYDrDuNN5L1oiqjDZy9azBr6fuXElMHZ2V6TdVDEjhGeTGwwNVvgDRYd+CJSwE7Q5scynYHCg+dyrPKeSm0KtcjJG2GFANHVqhHO51kLUkesVeZmFFRj44YYio1XrPXtSouNCKijI2qJyWmgE/Oq+wVn+ZJaxius0YJOGxH2/7d/cpidQ28QkMd1lQ4rsLbidCaOkQrcvWv8kIKrUMB3m//SDId/uDKnQIjOXK1Rz+ecSR9Yb+tcNhr1rKvM3EmjdkFn6gP/V+QlJhMJghef2YyXcttrHOtmcl0EweskclkMplMJjOIHAc4z5Gs948N2wAAAABJRU5ErkJggg==>

[image2]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACoAAAAYCAYAAACMcW/9AAABo0lEQVR4Xu2WzysFURTHD7LwcyHZsVOUhYWVWEoodlaytbCjyJZspGQhOxvK34DFW5MfKSWyUJSQ35LffE/n3PeO25sn9cxQ86lP79z7vW/mvjt35g1RTMz/Yg7ewg/jqWY58MzLLmG75pHgJpKOBElW6gdhwyvHE9n0AyXTjwiVfpKJdPqBwtmT3xkFvCeDVqyZJBv1gyhwl7YLdpDcLG3qqmYFydERwhPZg4OeQ5oFrXaouP0Z9Mj5M/vznIJXrJEkG/ODKMh0aVdIskI/CJs8kon89Pm5Ad9J/gD24Qls/TKCaB6uwUPTdwxfTDuhny30zfaaIplItx+Q3OXpJloJc7WfbzamCt4lRxDdwBqtS2ATnNW2PV5QnWSR5MBX8AJewzfNiuC99nHGYx5JHl0We+AJSk2kTrNlkuP0uUGgWDOmjFLnZNZNnTWq4YNp88nzteZVPjKZhV+AxrWehNMmqzd11liAI6btVmkY1pJcBUc57NV6CfZovQ0HtObV/xVeSfapg7fIjmnPwF2S18cG08/feYZbsILkBjrQOibm3/EJwkVyQROS3egAAAAASUVORK5CYII=>

[image3]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADYAAAAYCAYAAACx4w6bAAACL0lEQVR4Xu2XO2hUURCGJ5rGt4XBwlaNooUGC4kKsUs0RrCwtBMLS8G0QcHSFxjFQgQTgl0qCVpoYxHxiYKICCsKamKMr8KAr//PzHEn495bhJuwC/eDj5wz/yU5j3vOZkVKSkrmkyvwK/zj/GBZExwL2Se4x/KGIA28FrdFs+UxqHe4Mxz4wxgYeZOua46KDrwnBgazqVhsBHimsnZkl2h2IgaNQHrV9sO9opdDlzlq2aJ/TzcQHPgLeCx43LKs3axr0vnKusJnc76WxkLB7IBv4UgMPOOSvSPtotnJGOSwAv6OxTngHdwZi568V+2WaLY4BjmcgedicQ7IGvM0C0UfmM3n1zr4ET6BrVZLz9P3ViOc6F34Raqr/BL+gp1wAF62OrkG78GKq5Eb8Cq8LtnjmoarywcOxkD0FsybWKofhhdr1BPP4W7XZ85FSYu6BV6Cjyzn5DdYe5lUF4L/9rVZ+xS8Y+0ZDMFvcBJOwM+iq0eWwO9WY8Znfoh+FHjSpDmoxEqZeb5a5P+J+n7MNlvtpugYjlh9vdUTvDg6XL8wuNrkgOgf3GT90/C8tUk/fOD626U6QL6+3AUPP17ehBo5C1+5flyQwuAvbrZ2xdW566tFLxtOohs+dflPuMbag7DXZWSj6BuSWAUPiV7v/BZC+JqmiW21n4XBFXwmuoprXX0fvA/7XG1Y9Pzw6w5f1QQnucD1ExdEzyV3c5urvxbdfZ45nsPHLispKZkH/gJMcZNbgguGWQAAAABJRU5ErkJggg==>