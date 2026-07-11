<script>
	import { _ } from 'svelte-i18n';
	import StatusBadge from './StatusBadge.svelte';

	let {
		integrations = [],
		setupMode = false,
		onconnect = undefined,
		ondisconnect = undefined,
		onauthorize = undefined
	} = $props();

	let gmailIntegration = $derived(integrations.find((i) => i.provider === 'gmail'));
	let outlookIntegration = $derived(integrations.find((i) => i.provider === 'outlook'));
	let gcalIntegration = $derived(integrations.find((i) => i.provider === 'google_calendar'));
	let photosIntegration = $derived(integrations.find((i) => i.provider === 'google_photos'));

	let gmailConnected = $derived(gmailIntegration?.status === 'active');
	let outlookConnected = $derived(outlookIntegration?.status === 'active');
	let gcalConnected = $derived(gcalIntegration?.status === 'active');
	let photosConnected = $derived(photosIntegration?.status === 'active');
	let emailConnected = $derived(gmailConnected || outlookConnected);
	let fullyConnected = $derived(emailConnected && gcalConnected);
	let partiallyConnected = $derived(emailConnected || gcalConnected || photosConnected);

	let services = $derived([
		{ key: 'gmail', label: $_('integrations.gmail'), description: $_('integrations.gmailDescription') },
		{ key: 'outlook', label: $_('integrations.outlook'), description: $_('integrations.outlookDescription') },
		{
			key: 'google_calendar',
			label: $_('integrations.googleCalendar'),
			description: $_('integrations.googleCalendarDescription')
		},
		{
			key: 'google_photos',
			label: $_('integrations.googlePhotos'),
			description: $_('integrations.googlePhotosDescription')
		}
	]);

	/** @param {string} key */
	function getIntegrationForService(key) {
		return integrations.find((i) => i.provider === key);
	}
</script>

{#if setupMode && !partiallyConnected}
	<div class="flex flex-col items-center justify-center py-16 px-4 text-center">
		<h2 class="text-2xl font-bold mb-2">{$_('integrations.welcomeTitle')}</h2>
		<p class="text-base-content/70 max-w-md mb-6">
			{$_('integrations.welcomeDescription')}
		</p>
		<button class="btn btn-primary" onclick={onconnect}>{$_('integrations.connectGoogle')}</button>
	</div>
{:else}
	<div class="space-y-4">
		{#if setupMode}
			<h2 class="text-xl font-bold mb-4">{$_('integrations.connectAccounts')}</h2>
		{/if}
		{#each services as service}
			{@const integration = getIntegrationForService(service.key)}
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
								onclick={() => ondisconnect?.(integration.id)}
							>
								{$_('integrations.disconnect')}
							</button>
						{/if}
						{#if integration.status !== 'active'}
							<button
								class="btn btn-primary btn-sm"
								onclick={() => onauthorize?.(service.key)}
							>
								{$_('integrations.reconnect')}
							</button>
						{/if}
					{:else}
						<StatusBadge status="not_connected" type="integration" />
						<button
							class="btn btn-primary btn-sm"
							onclick={() => onauthorize?.(service.key)}
						>
							{$_('integrations.connect')}
						</button>
					{/if}
				</div>
			</div>
		{/each}
	</div>
{/if}
