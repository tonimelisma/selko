<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { user } from '$lib/stores.js';
	import { supabase } from '$lib/supabase.js';
	import { fetchIntegrations, disconnectIntegration } from '$lib/services/integrations.js';
	import { getCalendarSettings, updateCalendarSettings } from '$lib/services/calendar-settings.js';
	import { listCalendars, initiateGmailAuth, initiateCalendarAuth } from '$lib/api/backend.js';
	import IntegrationStatus from '$lib/components/IntegrationStatus.svelte';
	import ConfirmModal from '$lib/components/ConfirmModal.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';

	/** @type {any[]} */
	let integrationsList = $state([]);
	/** @type {any[]} */
	let calendars = $state([]);
	let selectedCalendar = $state('');
	let currentUserEmail = $state('');
	let isLoading = $state(true);
	let isLoadingCalendars = $state(false);
	let error = $state('');

	// Disconnect confirm modal
	let showDisconnectModal = $state(false);
	let disconnectTargetId = $state('');
	let disconnectTargetName = $state('');

	onMount(() => {
		const unsub = user.subscribe((u) => {
			currentUserEmail = u?.email || '';
		});

		loadData();

		return unsub;
	});

	async function loadData() {
		isLoading = true;
		error = '';

		const [intResult, settingsResult] = await Promise.all([
			fetchIntegrations(),
			getCalendarSettings()
		]);

		if (intResult.error) {
			error = intResult.error.message;
		} else {
			integrationsList = intResult.data;
		}

		if (settingsResult.data?.target_calendar_id) {
			selectedCalendar = settingsResult.data.target_calendar_id;
		}

		isLoading = false;

		// Load calendars if Google Calendar is connected
		const gcal = integrationsList.find(
			(i) => i.provider === 'google_calendar' && i.status === 'active'
		);
		if (gcal) {
			await loadCalendars();
		}
	}

	async function loadCalendars() {
		isLoadingCalendars = true;
		const result = await listCalendars();
		if (result.data) {
			calendars = result.data;
			// If no calendar selected, find the primary one
			if (!selectedCalendar) {
				const primary = calendars.find((c) => c.is_primary);
				if (primary) selectedCalendar = primary.id;
			}
		}
		isLoadingCalendars = false;
	}

	/** @param {any} event */
	async function handleCalendarChange(event) {
		const calendarId = event.target.value;
		selectedCalendar = calendarId;
		const result = await updateCalendarSettings({ target_calendar_id: calendarId });
		if (result.error) {
			error = result.error.message;
		}
	}

	/** @param {string} integrationId */
	function handleDisconnectRequest(integrationId) {
		const integration = integrationsList.find((i) => i.id === integrationId);
		disconnectTargetId = integrationId;
		disconnectTargetName = integration?.provider === 'gmail' ? 'Gmail' : 'Google Calendar';
		showDisconnectModal = true;
	}

	async function handleDisconnectConfirm() {
		showDisconnectModal = false;
		const { error: disconnectError } = await disconnectIntegration(disconnectTargetId);
		if (disconnectError) {
			error = disconnectError.message;
			return;
		}
		integrationsList = integrationsList.filter((i) => i.id !== disconnectTargetId);
		disconnectTargetId = '';
	}

	function handleDisconnectCancel() {
		showDisconnectModal = false;
		disconnectTargetId = '';
	}

	/** @param {string} provider */
	function handleAuthorize(provider) {
		if (provider === 'gmail') {
			initiateGmailAuth();
		} else if (provider === 'google_calendar') {
			initiateCalendarAuth();
		}
	}

	async function handleLogout() {
		await supabase.auth.signOut();
		goto('/login');
	}
</script>

<PageHeader title="Settings" />

{#if isLoading}
	<div class="flex items-center justify-center py-16">
		<span class="loading loading-spinner loading-lg"></span>
	</div>
{:else}
	{#if error}
		<div class="alert alert-error mb-4">
			<span>{error}</span>
		</div>
	{/if}

	<div class="space-y-8">
		<!-- Section 1: Connected Accounts -->
		<section>
			<h2 class="text-lg font-semibold mb-4">Connected Accounts</h2>
			<IntegrationStatus
				integrations={integrationsList}
				setupMode={false}
				ondisconnect={handleDisconnectRequest}
				onauthorize={handleAuthorize}
			/>
		</section>

		<!-- Section 2: Calendar Defaults -->
		<section>
			<h2 class="text-lg font-semibold mb-4">Calendar Defaults</h2>
			{#if isLoadingCalendars}
				<div class="h-12 bg-base-200 rounded animate-pulse"></div>
			{:else if calendars.length > 0}
				<div class="form-control max-w-md">
					<label class="label" for="target-calendar">
						<span class="label-text">Target Calendar</span>
					</label>
					<select
						id="target-calendar"
						class="select select-bordered w-full"
						value={selectedCalendar}
						onchange={handleCalendarChange}
					>
						{#each calendars as calendar}
							<option value={calendar.id}>
								{calendar.name}{calendar.is_primary ? ' (Primary)' : ''}
							</option>
						{/each}
					</select>
					<label class="label" for="target-calendar">
						<span class="label-text-alt text-base-content/60">
							Approved events will be added to this calendar
						</span>
					</label>
				</div>
			{:else}
				<p class="text-base-content/60">
					Connect Google Calendar to configure calendar defaults.
				</p>
			{/if}
		</section>

		<!-- Section 3: Account -->
		<section>
			<h2 class="text-lg font-semibold mb-4">Account</h2>
			<div class="space-y-4">
				<div class="form-control max-w-md">
					<label class="label" for="account-email">
						<span class="label-text">Email</span>
					</label>
					<input
						id="account-email"
						type="email"
						value={currentUserEmail}
						class="input input-bordered w-full"
						readonly
					/>
				</div>
				<div class="lg:hidden">
					<button class="btn btn-ghost" onclick={handleLogout}>Logout</button>
				</div>
			</div>
		</section>
	</div>
{/if}

<ConfirmModal
	open={showDisconnectModal}
	title="Disconnect {disconnectTargetName}"
	description="Are you sure you want to disconnect {disconnectTargetName}? You will need to re-authorize to use it again."
	confirmText="Disconnect"
	confirmClass="btn-error"
	onconfirm={handleDisconnectConfirm}
	oncancel={handleDisconnectCancel}
/>
