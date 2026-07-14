<script>
	import { _ } from 'svelte-i18n';
	import StatusBadge from './StatusBadge.svelte';
	import ErrorAlert from './ErrorAlert.svelte';

	let {
		integrations = [],
		setupMode = false,
		onconnect = undefined,
		ondisconnect = undefined,
		onauthorize = undefined
	} = $props();

	/** @type {string | null} */
	let connectingKey = $state(null);
	let connectError = $state('');

	let gmailIntegration = $derived(integrations.find((i) => i.provider === 'gmail'));
	let outlookIntegration = $derived(integrations.find((i) => i.provider === 'outlook'));
	let gcalIntegration = $derived(integrations.find((i) => i.provider === 'google_calendar'));

	let gmailConnected = $derived(gmailIntegration?.status === 'active');
	let outlookConnected = $derived(outlookIntegration?.status === 'active');
	let gcalConnected = $derived(gcalIntegration?.status === 'active');
	let emailConnected = $derived(gmailConnected || outlookConnected);
	let fullyConnected = $derived(emailConnected && gcalConnected);
	let partiallyConnected = $derived(emailConnected || gcalConnected);

	let services = $derived([
		{ key: 'gmail', label: $_('integrations.gmail'), description: $_('integrations.gmailDescription') },
		{ key: 'outlook', label: $_('integrations.outlook'), description: $_('integrations.outlookDescription') },
		{
			key: 'google_calendar',
			label: $_('integrations.googleCalendar'),
			description: $_('integrations.googleCalendarDescription')
		}
	]);

	/** @param {string} key */
	function getIntegrationForService(key) {
		return integrations.find((i) => i.provider === key);
	}

	/**
	 * @param {string} key
	 * @param {(() => void | Promise<void>) | undefined} action
	 */
	async function startConnect(key, action) {
		if (connectingKey || !action) return;
		connectingKey = key;
		connectError = '';
		try {
			await action();
		} catch (err) {
			connectError =
				err instanceof Error && err.message
					? err.message
					: $_('integrations.connectFailed');
			connectingKey = null;
		}
		// On success, page navigates away to Google — leave spinner until unload
	}

	/** @param {string} provider */
	async function authorizeProvider(provider) {
		await startConnect(provider, async () => {
			await onauthorize?.(provider);
		});
	}
</script>

{#if connectError}
	<ErrorAlert message={connectError} />
{/if}

{#if setupMode && !partiallyConnected}
	<div class="warm-card flex flex-col items-center justify-center px-4 py-16 text-center">
		<div class="mb-5 grid h-14 w-14 place-items-center rounded-[18px] bg-base-200 text-primary">
			<svg xmlns="http://www.w3.org/2000/svg" class="h-7 w-7" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M4 7.5A2.5 2.5 0 0 1 6.5 5h11A2.5 2.5 0 0 1 20 7.5v9a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 16.5v-9ZM8 9h8M8 13h5" /></svg>
		</div>
		<h2 class="mb-2 text-2xl font-extrabold tracking-tight">{$_('integrations.welcomeTitle')}</h2>
		<p class="mb-6 max-w-md text-sm text-base-content/65">
			{$_('integrations.welcomeDescription')}
		</p>
		<button
		class="btn btn-primary rounded-[14px] shadow-brand"
			disabled={connectingKey !== null}
			aria-busy={connectingKey === 'welcome'}
			onclick={() => startConnect('welcome', onconnect)}
		>
			{#if connectingKey === 'welcome'}
				<span class="loading loading-spinner loading-sm" aria-hidden="true"></span>
				{$_('integrations.connecting')}
			{:else}
				{$_('integrations.connectGoogle')}
			{/if}
		</button>
	</div>
{:else}
	<div class="space-y-4">
		{#if setupMode}
			<h2 class="text-xl font-bold mb-4">{$_('integrations.connectAccounts')}</h2>
		{/if}
		{#each services as service}
			{@const integration = getIntegrationForService(service.key)}
			{@const isConnecting = connectingKey === service.key}
			<div class="warm-card flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between">
				<div class="flex min-w-0 items-center gap-3">
					<div class="grid h-10 w-10 shrink-0 place-items-center rounded-[12px] bg-base-200 text-sm font-extrabold text-primary">{service.label.slice(0, 1)}</div>
					<div class="min-w-0">
					<h3 class="font-bold">{service.label}</h3>
					<p class="text-sm text-base-content/60">{service.description}</p>
					{#if integration?.provider_email}
						<p class="mt-1 text-sm text-base-content/50">{integration.provider_email}</p>
					{/if}
				</div>
				</div>
				<div class="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">
					{#if integration}
						<StatusBadge status={integration.status} type="integration" />
						{#if !setupMode}
							<button
								class="btn btn-outline btn-error btn-sm rounded-[11px]"
								disabled={connectingKey !== null}
								onclick={() => ondisconnect?.(integration.id)}
							>
								{$_('integrations.disconnect')}
							</button>
						{/if}
						{#if integration.status !== 'active'}
							<button
								class="btn btn-primary btn-sm rounded-[11px] shadow-brand"
								disabled={connectingKey !== null}
								aria-busy={isConnecting}
								onclick={() => authorizeProvider(service.key)}
							>
								{#if isConnecting}
									<span class="loading loading-spinner loading-sm" aria-hidden="true"></span>
									{$_('integrations.connecting')}
								{:else}
									{$_('integrations.reconnect')}
								{/if}
							</button>
						{/if}
					{:else}
						<StatusBadge status="not_connected" type="integration" />
						<button
							class="btn btn-primary btn-sm rounded-[11px] shadow-brand"
							disabled={connectingKey !== null}
							aria-busy={isConnecting}
							onclick={() => authorizeProvider(service.key)}
						>
							{#if isConnecting}
								<span class="loading loading-spinner loading-sm" aria-hidden="true"></span>
								{$_('integrations.connecting')}
							{:else}
								{$_('integrations.connect')}
							{/if}
						</button>
					{/if}
				</div>
			</div>
		{/each}
	</div>
{/if}
