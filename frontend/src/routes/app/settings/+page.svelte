<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { _ } from 'svelte-i18n';
	import { user } from '$lib/stores.js';
	import { supabase } from '$lib/supabase.js';
	import { fetchIntegrations, disconnectIntegration } from '$lib/services/integrations.js';
	import { getCalendarSettings, updateCalendarSettings } from '$lib/services/calendar-settings.js';
	import {
		listCalendars,
		initiateGmailAuth,
		initiateOutlookAuth,
		initiateCalendarAuth
	} from '$lib/api/backend.js';
	import { fetchEmailFolders, updateEmailFolder } from '$lib/services/email-folders.js';
	import IntegrationStatus from '$lib/components/IntegrationStatus.svelte';
	import ConfirmModal from '$lib/components/ConfirmModal.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import SenderRulesPanel from '$lib/components/SenderRulesPanel.svelte';
	import ErrorAlert from '$lib/components/ErrorAlert.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import LabeledSwitch from '$lib/components/LabeledSwitch.svelte';

	/** @type {any[]} */
	let integrationsList = $state([]);
	/** @type {any[]} */
	let calendars = $state([]);
	let selectedCalendar = $state('');
	/** @type {'all_day' | 'day_9_to_5' | 'morning_8_to_9' | 'custom'} */
	let allDayDisplayMode = $state('all_day');
	let allDayCustomStart = $state('09:00');
	let allDayCustomEnd = $state('17:00');
	let allDayCustomError = $state('');
	let isSavingAllDay = $state(false);
	let currentUserEmail = $state('');
	let isLoading = $state(true);
	let isLoadingCalendars = $state(false);
	let error = $state('');
	/** @type {{gmail: any[], outlook: any[]}} */
	let emailFolders = $state({ gmail: [], outlook: [] });
	let updatingFolderIds = $state(new Set());
	/** @type {Record<string, { message: string, nextIncluded: boolean } | null>} */
	let folderErrors = $state({});

	// Disconnect confirm modal
	let showDisconnectModal = $state(false);
	let disconnectTargetId = $state('');
	let disconnectTargetName = $state('');

	/** @param {string | null | undefined} value */
	function toTimeInputValue(value) {
		if (!value) return '';
		return String(value).slice(0, 5);
	}

	function allDayPreviewWindow() {
		if (allDayDisplayMode === 'all_day') return $_('settings.dateOnlyAllDay');
		if (allDayDisplayMode === 'day_9_to_5') return $_('settings.dateOnlyDay9to5');
		if (allDayDisplayMode === 'morning_8_to_9') return $_('settings.dateOnlyMorning8to9');
		const start = toTimeInputValue(allDayCustomStart) || '—';
		const end = toTimeInputValue(allDayCustomEnd) || '—';
		return `${start}–${end}`;
	}

	function customTimesValid() {
		if (allDayDisplayMode !== 'custom') return true;
		const start = toTimeInputValue(allDayCustomStart);
		const end = toTimeInputValue(allDayCustomEnd);
		if (!start || !end) return false;
		return end > start;
	}

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
		if (settingsResult.data?.all_day_display_mode) {
			allDayDisplayMode = settingsResult.data.all_day_display_mode;
		}
		if (settingsResult.data?.all_day_custom_start) {
			allDayCustomStart = toTimeInputValue(settingsResult.data.all_day_custom_start);
		}
		if (settingsResult.data?.all_day_custom_end) {
			allDayCustomEnd = toTimeInputValue(settingsResult.data.all_day_custom_end);
		}

		isLoading = false;
		await loadEmailFolders();

		// Load calendars if Google Calendar is connected
		const gcal = integrationsList.find(
			(i) => i.provider === 'google_calendar' && i.status === 'active'
		);
		if (gcal) {
			await loadCalendars();
		}
	}

	async function loadEmailFolders() {
		/** @type {Array<'gmail' | 'outlook'>} */
		const providers = /** @type {Array<'gmail' | 'outlook'>} */ (['gmail', 'outlook'].filter((provider) =>
			integrationsList.some((integration) => integration.provider === provider && integration.status === 'active')
		));
		const results = await Promise.all(providers.map((provider) => fetchEmailFolders(provider)));
		/** @type {{gmail: any[], outlook: any[]}} */
		const next = { gmail: [], outlook: [] };
		for (let index = 0; index < providers.length; index += 1) {
			const folderResult = results[index];
			if (!folderResult.error && folderResult.data) {
				next[providers[index]] = folderResult.data;
			}
		}
		emailFolders = next;
	}

	/** @param {string} provider @param {any} folder @param {boolean} nextIncluded */
	async function handleFolderChange(provider, folder, nextIncluded) {
		if (provider !== 'gmail' && provider !== 'outlook') return;
		if (updatingFolderIds.has(folder.id)) return;
		const previous = folder.is_included;
		updatingFolderIds = new Set([...updatingFolderIds, folder.id]);
		folderErrors = { ...folderErrors, [folder.id]: null };
		emailFolders = {
			...emailFolders,
			[provider]: emailFolders[provider].map((item) => item.id === folder.id ? { ...item, is_included: nextIncluded } : item)
		};
		const result = await updateEmailFolder(provider, folder.id, nextIncluded);
		if (result.error) {
			folderErrors = { ...folderErrors, [folder.id]: { message: result.error.message, nextIncluded } };
			emailFolders = {
				...emailFolders,
				[provider]: emailFolders[provider].map((item) => item.id === folder.id ? { ...item, is_included: previous } : item)
			};
		} else {
			emailFolders = {
				...emailFolders,
				[provider]: emailFolders[provider].map((item) =>
					item.id === folder.id ? { ...item, ...result.data } : item
				)
			};
		}
		const nextUpdating = new Set(updatingFolderIds);
		nextUpdating.delete(folder.id);
		updatingFolderIds = nextUpdating;
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

	/** @param {any} event */
	async function handleAllDayModeChange(event) {
		/** @type {'all_day' | 'day_9_to_5' | 'morning_8_to_9' | 'custom'} */
		const mode = event.target.value;
		allDayDisplayMode = mode;
		allDayCustomError = '';
		if (mode === 'custom') {
			if (!customTimesValid()) {
				allDayCustomError = $_('settings.dateOnlyCustomError');
				return;
			}
		}
		await saveAllDayPreference();
	}

	async function handleCustomTimeChange() {
		allDayCustomError = '';
		if (!customTimesValid()) {
			allDayCustomError = $_('settings.dateOnlyCustomError');
			return;
		}
		if (allDayDisplayMode !== 'custom') return;
		await saveAllDayPreference();
	}

	async function saveAllDayPreference() {
		isSavingAllDay = true;
		/** @type {Record<string, string>} */
		const payload = { all_day_display_mode: allDayDisplayMode };
		// Preserve custom times when switching presets by only sending them for custom
		// (and when the user edits them while in custom mode).
		if (allDayDisplayMode === 'custom') {
			payload.all_day_custom_start = toTimeInputValue(allDayCustomStart);
			payload.all_day_custom_end = toTimeInputValue(allDayCustomEnd);
		}
		const result = await updateCalendarSettings(payload);
		if (result.error) {
			error = result.error.message;
		}
		isSavingAllDay = false;
	}

	/** @param {string} integrationId */
	function handleDisconnectRequest(integrationId) {
		const integration = integrationsList.find((i) => i.id === integrationId);
		disconnectTargetId = integrationId;
		/** @type {Record<string, string>} */
		const providerNames = {
			gmail: $_('integrations.gmail'),
			outlook: $_('integrations.outlook'),
			google_calendar: $_('integrations.googleCalendar')
		};
		disconnectTargetName = providerNames[integration?.provider] || integration?.provider || '';
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
	async function handleAuthorize(provider) {
		if (provider === 'gmail') {
			await initiateGmailAuth();
		} else if (provider === 'outlook') {
			await initiateOutlookAuth();
		} else if (provider === 'google_calendar') {
			await initiateCalendarAuth();
		}
	}

	async function handleLogout() {
		await supabase.auth.signOut();
		goto('/login');
	}
</script>

<PageHeader title={$_('settings.title')} subtitle={$_('settings.subtitle')} />

{#if isLoading}
	<LoadingSpinner />
{:else}
	{#if error}
		<ErrorAlert message={error} />
	{/if}

	<div class="space-y-10">
		<!-- Section 1: Connected Accounts -->
		<section>
			<h2 class="mb-4 text-[11px] font-bold uppercase tracking-[0.08em] text-secondary">{$_('settings.connectAccount')}</h2>
			<h3 class="mb-3 text-lg font-extrabold">{$_('settings.connectedAccounts')}</h3>
			<IntegrationStatus
				integrations={integrationsList}
				setupMode={false}
				ondisconnect={handleDisconnectRequest}
				onauthorize={handleAuthorize}
			/>
		</section>

		<!-- Section 2: Email folders -->
		<section>
			<h2 class="mb-2 text-[11px] font-bold uppercase tracking-[0.08em] text-secondary">{$_('settings.emailFolders')}</h2>
			<p class="mb-4 text-sm text-base-content/60">{$_('settings.emailFoldersHint')}</p>
			{#if emailFolders.gmail.length === 0 && emailFolders.outlook.length === 0}
				<p class="text-sm text-base-content/60">{$_('settings.noEmailFolders')}</p>
			{:else}
				<div class="space-y-4 max-w-2xl">
					{#each [{ provider: 'gmail', label: $_('integrations.gmail'), folders: emailFolders.gmail }, { provider: 'outlook', label: $_('integrations.outlook'), folders: emailFolders.outlook }] as group}
						{#if group.folders.length > 0}
							<div>
								<h3 class="font-medium mb-2">{group.label}</h3>
								<div class="space-y-2">
									{#each group.folders as folder (folder.id)}
										{@const folderError = folderErrors[folder.id]}
										<div class="warm-card flex items-center justify-between gap-3 p-3">
											<div class="min-w-0">
											<div class="font-medium text-sm truncate">{folder.full_path}</div>
											{#if folder.classification_decision === 'exclude' && folder.classification_reason}
												<div class="text-xs text-base-content/60 mt-1">
													{$_('settings.folderRecommendation', { values: { reason: folder.classification_reason } })}
												</div>
												{/if}
												{#if folderError}
													<div class="mt-2 flex items-center gap-2 text-xs text-error" role="alert">
														<span>{folderError.message}</span>
														<button class="btn action-tertiary text-error" onclick={() => handleFolderChange(group.provider, folder, folderError.nextIncluded)}>{$_('common.retry')}</button>
													</div>
												{/if}
											</div>
										<LabeledSwitch
											checked={folder.is_included}
											disabled={updatingFolderIds.has(folder.id)}
											onchange={(/** @type {boolean} */ included) => handleFolderChange(group.provider, folder, included)}
										/>
									</div>
									{/each}
								</div>
							</div>
						{/if}
					{/each}
				</div>
			{/if}
		</section>

		<!-- Section 3: Calendar Defaults -->
		<section>
			<h2 class="mb-4 text-[11px] font-bold uppercase tracking-[0.08em] text-secondary">{$_('settings.calendarDefaults')}</h2>
			<div class="space-y-4 max-w-md">
				{#if isLoadingCalendars}
					<div class="h-12 bg-base-200 rounded animate-pulse"></div>
				{:else if calendars.length > 0}
					<div class="warm-card p-4">
						<label class="label" for="target-calendar">
							<span class="label-text">{$_('settings.targetCalendar')}</span>
						</label>
						<select
							id="target-calendar"
							class="select select-bordered w-full bg-base-100"
							value={selectedCalendar}
							onchange={handleCalendarChange}
						>
							{#each calendars as calendar}
								<option value={calendar.id}>
									{calendar.name}{calendar.is_primary ? ' ' + $_('settings.calendarPrimary') : ''}
								</option>
							{/each}
						</select>
						<label class="label" for="target-calendar">
							<span class="label-text-alt text-base-content/60">
								{$_('settings.targetCalendarHint')}
							</span>
						</label>
					</div>
				{:else}
					<p class="text-base-content/60">
						{$_('settings.connectCalendarPrompt')}
					</p>
				{/if}

				<div class="warm-card p-4">
					<label class="label" for="all-day-display-mode">
						<span class="label-text">{$_('settings.dateOnlyEvents')}</span>
					</label>
					<p class="mb-2 text-sm text-base-content/60">{$_('settings.dateOnlyEventsHint')}</p>
					<select
						id="all-day-display-mode"
						class="select select-bordered w-full bg-base-100"
						value={allDayDisplayMode}
						onchange={handleAllDayModeChange}
						disabled={isSavingAllDay}
					>
						<option value="all_day">{$_('settings.dateOnlyAllDay')}</option>
						<option value="day_9_to_5">{$_('settings.dateOnlyDay9to5')}</option>
						<option value="morning_8_to_9">{$_('settings.dateOnlyMorning8to9')}</option>
						<option value="custom">{$_('settings.dateOnlyCustom')}</option>
					</select>

					{#if allDayDisplayMode === 'custom'}
						<div class="mt-3 grid grid-cols-2 gap-3">
							<div>
								<label class="label" for="all-day-custom-start">
									<span class="label-text">{$_('settings.dateOnlyCustomStart')}</span>
								</label>
								<input
									id="all-day-custom-start"
									type="time"
									class="input input-bordered w-full bg-base-100"
									value={allDayCustomStart}
									onchange={(event) => {
										allDayCustomStart = event.currentTarget.value;
										handleCustomTimeChange();
									}}
									disabled={isSavingAllDay}
								/>
							</div>
							<div>
								<label class="label" for="all-day-custom-end">
									<span class="label-text">{$_('settings.dateOnlyCustomEnd')}</span>
								</label>
								<input
									id="all-day-custom-end"
									type="time"
									class="input input-bordered w-full bg-base-100"
									value={allDayCustomEnd}
									onchange={(event) => {
										allDayCustomEnd = event.currentTarget.value;
										handleCustomTimeChange();
									}}
									disabled={isSavingAllDay}
								/>
							</div>
						</div>
						{#if allDayCustomError}
							<p class="mt-2 text-sm text-error" role="alert">{allDayCustomError}</p>
						{/if}
					{/if}

					<p class="mt-3 text-sm text-base-content/60">
						{$_('settings.dateOnlyPreview', { values: { window: allDayPreviewWindow() } })}
					</p>
				</div>
			</div>
		</section>

		<!-- Section 4: Automation Rules -->
		<section>
			<h2 class="mb-4 text-[11px] font-bold uppercase tracking-[0.08em] text-secondary">{$_('settings.automationRules')}</h2>
			<SenderRulesPanel />
		</section>

		<!-- Section 5: Account -->
		<section>
			<h2 class="mb-4 text-[11px] font-bold uppercase tracking-[0.08em] text-secondary">{$_('settings.account')}</h2>
			<div class="space-y-4">
				<div class="warm-card max-w-md p-4">
					<p class="text-xs font-semibold text-base-content/65">{$_('auth.emailLabel')}</p>
					<p class="mt-1 text-sm font-semibold">{currentUserEmail}</p>
				</div>
				<button class="btn btn-outline btn-error w-full sm:w-auto lg:hidden" onclick={handleLogout}>{$_('auth.logOut')}</button>
			</div>
		</section>
	</div>
{/if}

<ConfirmModal
	open={showDisconnectModal}
	title={$_('settings.disconnectTitle', { values: { name: disconnectTargetName } })}
	description={$_('settings.disconnectDescription', { values: { name: disconnectTargetName } })}
	confirmText={$_('settings.disconnect')}
	confirmClass="btn-error"
	onconfirm={handleDisconnectConfirm}
	oncancel={handleDisconnectCancel}
/>
