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
	<div class="flex flex-col items-center justify-center py-16 px-4 text-center">
		<h2 class="text-2xl font-bold mb-2">{$_('integrations.welcomeTitle')}</h2>
		<p class="text-base-content/70 max-w-md mb-6">
			{$_('integrations.welcomeDescription')}
		</p>
		<button
			class="btn btn-primary"
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
			<div class="flex items-center justify-between p-4 bg-base-200 rounded-lg gap-2">
				<div class="min-w-0">
					<h3 class="font-semibold">{service.label}</h3>
					<p class="text-sm text-base-content/70">{service.description}</p>
					{#if integration?.provider_email}
						<p class="text-sm text-base-content/50 mt-1">{integration.provider_email}</p>
					{/if}
				</div>
				<div class="flex items-center gap-3 flex-shrink-0">
					{#if integration}
						<StatusBadge status={integration.status} type="integration" />
						{#if !setupMode}
							<button
								class="btn btn-outline btn-error btn-sm"
								disabled={connectingKey !== null}
								onclick={() => ondisconnect?.(integration.id)}
							>
								{$_('integrations.disconnect')}
							</button>
						{/if}
						{#if integration.status !== 'active'}
							<button
								class="btn btn-primary btn-sm"
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
							class="btn btn-primary btn-sm"
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
