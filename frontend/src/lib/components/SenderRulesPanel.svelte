<script>
	import { onMount } from 'svelte';
	import { _ } from 'svelte-i18n';
	import { fetchSenderRules, createSenderRule, deleteSenderRule } from '$lib/services/sender-rules.js';
	import ConfirmModal from './ConfirmModal.svelte';
	import ErrorAlert from './ErrorAlert.svelte';
	import RemovableChip from './RemovableChip.svelte';

	/** @type {import('$lib/services/sender-rules.js').SenderRule[]} */
	let rules = $state([]);
	let isLoading = $state(true);
	let error = $state('');

	// Add rule form
	let newSenderInput = $state('');
	let newAction = $state('ignore');
	let isAdding = $state(false);
	let ignoredRules = $derived(rules.filter((rule) => rule.action === 'ignore'));
	let approvedRules = $derived(rules.filter((rule) => rule.action === 'auto_approve'));

	// Delete confirmation
	let showDeleteModal = $state(false);
	let deleteTargetId = $state('');
	let deleteTargetLabel = $state('');

	onMount(async () => {
		await loadRules();
	});

	async function loadRules() {
		isLoading = true;
		error = '';
		const result = await fetchSenderRules();
		if (result.error) {
			error = result.error.message;
		} else {
			rules = result.data;
		}
		isLoading = false;
	}

	async function handleAddRule() {
		if (!newSenderInput.trim()) return;

		isAdding = true;
		error = '';

		const input = newSenderInput.trim();
		/** @type {{ sender_email?: string, sender_domain?: string, action: import('$lib/services/sender-rules.js').SenderRuleAction }} */
		const rule = input.includes('@')
			? { sender_email: input, action: /** @type {import('$lib/services/sender-rules.js').SenderRuleAction} */ (newAction) }
			: { sender_domain: input, action: /** @type {import('$lib/services/sender-rules.js').SenderRuleAction} */ (newAction) };

		const result = await createSenderRule(rule);
		if (result.error) {
			error = result.error.message;
		} else if (result.data) {
			rules = [result.data, ...rules];
			newSenderInput = '';
			newAction = 'ignore';
		}
		isAdding = false;
	}

	/** @param {import('$lib/services/sender-rules.js').SenderRule} rule */
	function handleDeleteRequest(rule) {
		deleteTargetId = rule.id;
		deleteTargetLabel = rule.sender_email || rule.sender_domain || '';
		showDeleteModal = true;
	}

	async function handleDeleteConfirm() {
		showDeleteModal = false;
		const { error: deleteError } = await deleteSenderRule(deleteTargetId);
		if (deleteError) {
			error = deleteError.message;
			return;
		}
		rules = rules.filter((r) => r.id !== deleteTargetId);
		deleteTargetId = '';
		deleteTargetLabel = '';
	}

	function handleDeleteCancel() {
		showDeleteModal = false;
		deleteTargetId = '';
		deleteTargetLabel = '';
	}
</script>

{#if isLoading}
	<div class="h-12 rounded-[14px] bg-base-200 animate-pulse"></div>
{:else}
	{#if error}
		<ErrorAlert message={error} />
	{/if}

	{#if rules.length === 0}
		<p class="mb-4 text-sm text-base-content/60">
			{$_('senderRules.noRules')}
		</p>
	{:else}
		<div class="mb-5 space-y-4">
			{#if approvedRules.length > 0}
				<div><p class="mb-2 text-xs font-bold uppercase tracking-[0.08em] semantic-status-success">{$_('senderRules.autoApprove')}</p><div class="flex flex-wrap gap-2">
					{#each approvedRules as rule (rule.id)}<RemovableChip tone="success" category={$_('senderRules.autoApprove')} label={rule.sender_email || rule.sender_domain || ''} removeLabel={$_('senderRules.deleteRuleLabel', { values: { label: rule.sender_email || rule.sender_domain || '' } })} onremove={() => handleDeleteRequest(rule)} />{/each}
				</div></div>
			{/if}
			{#if ignoredRules.length > 0}
				<div><p class="mb-2 text-xs font-bold uppercase tracking-[0.08em] text-error">{$_('senderRules.ignore')}</p><div class="flex flex-wrap gap-2">
					{#each ignoredRules as rule (rule.id)}<RemovableChip tone="error" category={$_('senderRules.ignore')} label={rule.sender_email || rule.sender_domain || ''} removeLabel={$_('senderRules.deleteRuleLabel', { values: { label: rule.sender_email || rule.sender_domain || '' } })} onremove={() => handleDeleteRequest(rule)} />{/each}
				</div></div>
			{/if}
		</div>
	{/if}

	<!-- Add rule form -->
	<div class="flex max-w-2xl flex-col gap-2 sm:flex-row">
		<div class="form-control flex-1">
			<input
				type="text"
				class="input input-bordered input-sm w-full bg-base-100"
				placeholder={$_('senderRules.senderPlaceholder')}
				bind:value={newSenderInput}
				onkeydown={(e) => { if (e.key === 'Enter') handleAddRule(); }}
			/>
		</div>
		<select
			class="select select-bordered select-sm bg-base-100"
			bind:value={newAction}
			aria-label={$_('senderRules.ruleAction')}
		>
			<option value="ignore">{$_('senderRules.ignore')}</option>
			<option value="auto_approve">{$_('senderRules.autoApprove')}</option>
		</select>
		<button
		class="btn btn-primary shadow-brand"
			onclick={handleAddRule}
			disabled={isAdding || !newSenderInput.trim()}
		>
			{#if isAdding}
				<span class="loading loading-spinner loading-xs"></span>
			{/if}
			{$_('senderRules.addRule')}
		</button>
	</div>
{/if}

<ConfirmModal
	open={showDeleteModal}
	title={$_('senderRules.deleteRuleTitle')}
	description={$_('senderRules.deleteRuleDescription', { values: { label: deleteTargetLabel } })}
	confirmText={$_('common.delete')}
	confirmClass="btn-error"
	onconfirm={handleDeleteConfirm}
	oncancel={handleDeleteCancel}
/>
