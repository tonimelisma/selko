<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { getEvent, updateEvent, updateEventStatus } from '$lib/services/events.js';
	import { fetchEventSources } from '$lib/services/event-sources.js';
	import { getEmail } from '$lib/services/emails.js';
	import { fetchAttachments } from '$lib/services/attachments.js';
	import { syncEventToCalendar } from '$lib/api/backend.js';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';

	let eventId = $state('');
	/** @type {any} */
	let event = $state(null);
	/** @type {any[]} */
	let sources = $state([]);
	/** @type {any} */
	let sourceEmail = $state(null);
	/** @type {any[]} */
	let attachments = $state([]);
	let isLoading = $state(true);
	let isSaving = $state(false);
	let error = $state('');
	let sourceExpanded = $state(false);

	// Form fields
	let title = $state('');
	let allDay = $state(false);
	let eventDate = $state('');
	let startTime = $state('');
	let endTime = $state('');
	let location = $state('');
	let description = $state('');

	$effect(() => {
		const unsub = page.subscribe((p) => {
			eventId = p.params.id || '';
		});
		return unsub;
	});

	onMount(async () => {
		if (!eventId) return;
		await loadEventData();
	});

	async function loadEventData() {
		isLoading = true;
		error = '';

		const [eventResult, sourcesResult] = await Promise.all([
			getEvent(eventId),
			fetchEventSources(eventId)
		]);

		if (eventResult.error) {
			error = eventResult.error.message;
			isLoading = false;
			return;
		}

		event = eventResult.data;
		sources = sourcesResult.data || [];

		// Populate form fields
		if (event) {
			title = event.title || '';
			allDay = event.all_day || false;
			location = event.location || '';
			description = event.description || '';

			if (event.start_datetime) {
				const start = new Date(event.start_datetime);
				eventDate = start.toISOString().split('T')[0];
				startTime = start.toTimeString().slice(0, 5);
			}
			if (event.end_datetime) {
				const end = new Date(event.end_datetime);
				endTime = end.toTimeString().slice(0, 5);
			}
		}

		// Load source email if available
		if (sources.length > 0 && sources[0].email_id) {
			const emailId = sources[0].email_id;
			const [emailResult, attachResult] = await Promise.all([
				getEmail(emailId),
				fetchAttachments(emailId)
			]);
			sourceEmail = emailResult.data;
			attachments = attachResult.data || [];
		}

		isLoading = false;
	}

	async function handleSave() {
		if (!event) return;
		isSaving = true;

		/** @type {Record<string, any>} */
		const updates = {
			title,
			all_day: allDay,
			location: location || undefined,
			description: description || undefined
		};

		if (eventDate) {
			if (allDay) {
				updates.start_datetime = `${eventDate}T00:00:00Z`;
				if (endTime) {
					updates.end_datetime = `${eventDate}T23:59:59Z`;
				}
			} else {
				if (startTime) {
					updates.start_datetime = `${eventDate}T${startTime}:00Z`;
				}
				if (endTime) {
					updates.end_datetime = `${eventDate}T${endTime}:00Z`;
				}
			}
		}

		const result = await updateEvent(event.id, updates);
		if (result.error) {
			error = result.error.message;
		} else {
			event = result.data;
		}
		isSaving = false;
	}

	async function handleApprove() {
		if (!event || !title) return;
		await handleSave();
		if (error) return;

		const { error: statusError } = await updateEventStatus(event.id, 'approved');
		if (statusError) {
			error = statusError.message;
			return;
		}
		syncEventToCalendar(event.id);
		goto('/app');
	}

	async function handleReject() {
		if (!event) return;
		const { error: statusError } = await updateEventStatus(event.id, 'rejected');
		if (statusError) {
			error = statusError.message;
			return;
		}
		goto('/app');
	}
</script>

{#if isLoading}
	<div class="flex items-center justify-center py-16">
		<span class="loading loading-spinner loading-lg"></span>
	</div>
{:else if error && !event}
	<div class="alert alert-error">
		<span>{error}</span>
		<a href="/app" class="btn btn-sm btn-ghost">Back to Review</a>
	</div>
{:else if event}
	<PageHeader title="Event Detail" backHref="/app">
		{#snippet children()}
			<StatusBadge status={event.status} />
		{/snippet}
	</PageHeader>

	{#if error}
		<div class="alert alert-error mb-4">
			<span>{error}</span>
		</div>
	{/if}

	<div class="grid grid-cols-1 lg:grid-cols-5 gap-6">
		<!-- Source email - desktop sidebar -->
		{#if sourceEmail}
			<div class="lg:col-span-2 order-2 lg:order-1">
				<!-- Desktop: always visible -->
				<div class="hidden lg:block">
					<div class="card bg-base-200">
						<div class="card-body">
							<h3 class="card-title text-sm">Source Email</h3>
							<div class="space-y-2 text-sm">
								<p><span class="font-medium">From:</span> {sourceEmail.from_name || sourceEmail.from_email}</p>
								<p><span class="font-medium">Subject:</span> {sourceEmail.subject || 'No subject'}</p>
								{#if sourceEmail.date_sent}
									<p><span class="font-medium">Date:</span> {new Date(sourceEmail.date_sent).toLocaleDateString()}</p>
								{/if}
								{#if sourceEmail.snippet}
									<div class="mt-3 p-3 bg-base-100 rounded text-base-content/70">
										{sourceEmail.snippet}
									</div>
								{/if}
								{#if attachments.length > 0}
									<div class="mt-3">
										<p class="font-medium">Attachments ({attachments.length})</p>
										<ul class="list-disc list-inside mt-1">
											{#each attachments as attachment}
												<li class="text-base-content/70">{attachment.filename}</li>
											{/each}
										</ul>
									</div>
								{/if}
							</div>
						</div>
					</div>
				</div>

				<!-- Mobile/Tablet: collapsible -->
				<div class="lg:hidden">
					<div class="collapse collapse-arrow bg-base-200">
						<input type="checkbox" bind:checked={sourceExpanded} />
						<div class="collapse-title font-medium">
							View Source Email
						</div>
						<div class="collapse-content">
							<div class="space-y-2 text-sm">
								<p><span class="font-medium">From:</span> {sourceEmail.from_name || sourceEmail.from_email}</p>
								<p><span class="font-medium">Subject:</span> {sourceEmail.subject || 'No subject'}</p>
								{#if sourceEmail.date_sent}
									<p><span class="font-medium">Date:</span> {new Date(sourceEmail.date_sent).toLocaleDateString()}</p>
								{/if}
								{#if sourceEmail.snippet}
									<div class="mt-3 p-3 bg-base-100 rounded text-base-content/70">
										{sourceEmail.snippet}
									</div>
								{/if}
								{#if attachments.length > 0}
									<div class="mt-3">
										<p class="font-medium">Attachments ({attachments.length})</p>
										<ul class="list-disc list-inside mt-1">
											{#each attachments as attachment}
												<li class="text-base-content/70">{attachment.filename}</li>
											{/each}
										</ul>
									</div>
								{/if}
							</div>
						</div>
					</div>
				</div>
			</div>
		{/if}

		<!-- Event form -->
		<div class="{sourceEmail ? 'lg:col-span-3' : 'lg:col-span-5'} order-1 lg:order-2">
			<form onsubmit={(e) => { e.preventDefault(); handleSave(); }} class="space-y-4 pb-24 lg:pb-0">
				<div class="form-control">
					<label class="label" for="event-title">
						<span class="label-text">Title</span>
					</label>
					<input
						id="event-title"
						type="text"
						bind:value={title}
						class="input input-bordered w-full"
						required
						onblur={handleSave}
					/>
				</div>

				<div class="form-control">
					<label class="label cursor-pointer justify-start gap-3" for="event-all-day">
						<input
							id="event-all-day"
							type="checkbox"
							bind:checked={allDay}
							class="checkbox"
							onchange={handleSave}
						/>
						<span class="label-text">All Day</span>
					</label>
				</div>

				<div class="form-control">
					<label class="label" for="event-date">
						<span class="label-text">Date</span>
					</label>
					<input
						id="event-date"
						type="date"
						bind:value={eventDate}
						class="input input-bordered w-full"
						required
						onblur={handleSave}
					/>
				</div>

				{#if !allDay}
					<div class="grid grid-cols-2 gap-4">
						<div class="form-control">
							<label class="label" for="event-start-time">
								<span class="label-text">Start Time</span>
							</label>
							<input
								id="event-start-time"
								type="time"
								bind:value={startTime}
								class="input input-bordered w-full"
								required
								onblur={handleSave}
							/>
						</div>
						<div class="form-control">
							<label class="label" for="event-end-time">
								<span class="label-text">End Time</span>
							</label>
							<input
								id="event-end-time"
								type="time"
								bind:value={endTime}
								class="input input-bordered w-full"
								onblur={handleSave}
							/>
						</div>
					</div>
				{/if}

				<div class="form-control">
					<label class="label" for="event-location">
						<span class="label-text">Location</span>
					</label>
					<input
						id="event-location"
						type="text"
						bind:value={location}
						class="input input-bordered w-full"
						placeholder="Optional"
						onblur={handleSave}
					/>
				</div>

				<div class="form-control">
					<label class="label" for="event-description">
						<span class="label-text">Description</span>
					</label>
					<textarea
						id="event-description"
						bind:value={description}
						class="textarea textarea-bordered w-full"
						rows="3"
						placeholder="Optional"
						onblur={handleSave}
					></textarea>
				</div>
			</form>

			<!-- Desktop action buttons -->
			{#if event.status === 'pending_review'}
				<div class="hidden lg:flex justify-end gap-3 mt-6">
					<button class="btn btn-ghost" onclick={handleReject}>Reject</button>
					<button class="btn btn-primary" onclick={handleApprove} disabled={!title}>
						Approve
					</button>
				</div>
			{/if}
		</div>
	</div>

	<!-- Mobile fixed bottom action bar -->
	{#if event.status === 'pending_review'}
		<div class="fixed bottom-20 left-0 right-0 bg-base-100 border-t border-base-300 p-4 lg:hidden">
			<div class="flex justify-end gap-3 max-w-7xl mx-auto">
				<button class="btn btn-ghost flex-1" onclick={handleReject}>Reject</button>
				<button class="btn btn-primary flex-1" onclick={handleApprove} disabled={!title}>
					Approve
				</button>
			</div>
		</div>
	{/if}
{/if}
