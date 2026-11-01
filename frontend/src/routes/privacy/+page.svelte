<script>
	import LogoMark from '$lib/components/LogoMark.svelte';

	const contactEmail = 'toni.melisma@gmail.com';
	const lastUpdated = 'October 31, 2026';
</script>

<svelte:head>
	<title>Privacy Policy · Selko</title>
	<meta name="description" content="How Selko collects, uses, stores and deletes your data." />
</svelte:head>

<main id="main-content" class="mx-auto max-w-2xl px-4 py-10 sm:py-14">
	<a href="/" class="mb-8 inline-flex items-center gap-2 text-base-content">
		<LogoMark size={32} />
		<span class="text-xl font-extrabold tracking-tight">Selko</span>
	</a>

	<h1 class="text-3xl font-extrabold tracking-tight">Privacy Policy</h1>
	<p class="mt-2 text-sm text-base-content/60">Last updated {lastUpdated}</p>

	<div class="mt-8 space-y-8 leading-relaxed">
		<section>
			<p>
				Selko reads the email accounts you connect, finds the events in them, and helps you put
				those events on your calendar. This policy explains what data that involves, what we do
				with it, who else handles it, and how to have it deleted.
			</p>
		</section>

		<section>
			<h2 class="text-xl font-bold">What we collect</h2>
			<ul class="mt-3 list-disc space-y-2 pl-6">
				<li>
					<strong>Your account:</strong> your email address and a password, which our
					authentication provider stores hashed.
				</li>
				<li>
					<strong>Email you connect:</strong> when you connect Gmail or Outlook, Selko reads
					messages in the folders you include: headers, body text, calendar invitations and
					attachments.
				</li>
				<li>
					<strong>Your calendar:</strong> when you connect Google Calendar, Selko creates,
					updates and cancels the events you approve.
				</li>
				<li>
					<strong>Connection tokens:</strong> the OAuth tokens Google or Microsoft issue so Selko
					can keep reading your mail without asking you to sign in again.
				</li>
				<li>
					<strong>What Selko derives:</strong> the events it extracts, your review decisions,
					and a processing history for each email.
				</li>
			</ul>
		</section>

		<section>
			<h2 class="text-xl font-bold">How we use it</h2>
			<p class="mt-3">
				We use your data only to provide Selko to you: to find events in your email, show them to
				you for review, and keep your calendar in step with what you approve. We do not sell your
				data, use it for advertising, or use it to build profiles of you. People do not read your
				email, except with your explicit permission for a specific message, when it is needed for
				security or to comply with the law.
			</p>
		</section>

		<section>
			<h2 class="text-xl font-bold">Google user data</h2>
			<p class="mt-3">
				Selko's use and transfer of information received from Google APIs to any other app will
				adhere to the
				<a
					class="link link-primary"
					href="https://developers.google.com/terms/api-services-user-data-policy"
					rel="noopener noreferrer"
					target="_blank">Google API Services User Data Policy</a
				>, including the Limited Use requirements.
			</p>
			<p class="mt-3">
				Selko requests read-only access to Gmail and access to manage events on Google Calendar.
				Gmail data is used only to find and update calendar events for you, and is transferred to
				others only as described under "Who else handles your data" below, which is needed to
				provide that feature. It is never used to train general-purpose AI models.
			</p>
		</section>

		<section>
			<h2 class="text-xl font-bold">AI processing</h2>
			<p class="mt-3">
				Selko uses large language models to read emails and attachments and extract events. The
				content of an email is sent to an AI provider's API for that purpose only. We use paid API
				services whose terms do not allow the provider to train its models on what we send.
			</p>
		</section>

		<section>
			<h2 class="text-xl font-bold">Who else handles your data</h2>
			<p class="mt-3">We share data only with the service providers that run Selko for us:</p>
			<ul class="mt-3 list-disc space-y-2 pl-6">
				<li><strong>Supabase:</strong> database, file storage and sign-in.</li>
				<li><strong>Render:</strong> hosting for the Selko web app and server.</li>
				<li>
					<strong>Anthropic:</strong> the AI model that extracts events from email content.
				</li>
				<li>
					<strong>Google:</strong> Gmail and Google Calendar for the accounts you connect, and
					the Gemini API as a backup AI model when Anthropic's is unavailable.
				</li>
				<li><strong>Microsoft:</strong> Outlook mail for the accounts you connect.</li>
			</ul>
			<p class="mt-3">
				We may also disclose data if the law requires it, or to a successor if Selko is
				transferred, in which case this policy continues to apply to your data.
			</p>
		</section>

		<section>
			<h2 class="text-xl font-bold">Storage and security</h2>
			<p class="mt-3">
				Data is encrypted in transit and stored with providers that encrypt it at rest. Each user
				can read only their own records. Connection tokens are used only by Selko's server.
			</p>
		</section>

		<section>
			<h2 class="text-xl font-bold">Keeping and deleting your data</h2>
			<p class="mt-3">
				We keep your data while your account exists. You can disconnect an email or calendar
				account in Settings at any time, which stops Selko reading it. You can also remove
				Selko's access from your
				<a
					class="link link-primary"
					href="https://myaccount.google.com/connections"
					rel="noopener noreferrer"
					target="_blank">Google account</a
				>
				or Microsoft account.
			</p>
			<p class="mt-3">
				To delete your account and all of its data, email
				<a class="link link-primary" href="mailto:{contactEmail}">{contactEmail}</a> from the address
				you signed up with. We delete it within 30 days, including stored email content, extracted
				events and connection tokens. Events Selko already added to your calendar stay there
				unless you remove them.
			</p>
		</section>

		<section>
			<h2 class="text-xl font-bold">Children</h2>
			<p class="mt-3">Selko is not intended for anyone under 16.</p>
		</section>

		<section>
			<h2 class="text-xl font-bold">Changes</h2>
			<p class="mt-3">
				If we change this policy, we will update the date above, and tell you in the app or by
				email before a change that affects how your existing data is used.
			</p>
		</section>

		<section>
			<h2 class="text-xl font-bold">Contact</h2>
			<p class="mt-3">
				Questions about privacy:
				<a class="link link-primary" href="mailto:{contactEmail}">{contactEmail}</a>.
			</p>
		</section>
	</div>
</main>
