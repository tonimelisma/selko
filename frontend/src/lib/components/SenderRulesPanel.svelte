<script>
	import { onMount } from 'svelte';
	import { fetchSenderRules, createSenderRule, deleteSenderRule } from '$lib/services/sender-rules.js';
	import ConfirmModal from './ConfirmModal.svelte';
	import ErrorAlert from './ErrorAlert.svelte';

	/** @type {import('$lib/services/sender-rules.js').SenderRule[]} */
	let rules = $state([]);
	let isLoading = $state(true);
	let error = $state('');

	// Add rule form
	let newSenderInput = $state('');
	let newAction = $state('ignore');
	let isAdding = $state(false);

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
	<div class="h-12 bg-base-200 rounded animate-pulse"></div>
{:else}
	{#if error}
		<ErrorAlert message={error} />
	{/if}

	{#if rules.length === 0}
		<p class="text-base-content/60 mb-4">
			No automation rules yet. Create rules from the review queue or add one below.
		</p>
	{:else}
		<div class="space-y-2 mb-4">
			{#each rules as rule (rule.id)}
				<div class="flex items-center justify-between p-3 bg-base-200 rounded">
					<div class="flex items-center gap-3">
						{#if rule.action === 'ignore'}
							<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-error" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" /></svg>
						{:else}
							<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-success" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
						{/if}
						<div>
							<span class="text-sm font-medium text-base-content">
								{rule.action === 'ignore' ? 'Ignore' : 'Auto-approve'}
							</span>
							<span class="text-sm text-base-content/60 ml-2">
								{rule.sender_email || rule.sender_domain}
							</span>
						</div>
					</div>
					<button
						class="btn btn-ghost btn-sm btn-square"
						aria-label="Delete rule for {rule.sender_email || rule.sender_domain}"
						onclick={() => handleDeleteRequest(rule)}
					>
						<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
					</button>
				</div>
			{/each}
		</div>
	{/if}

	<!-- Add rule form -->
	<div class="flex flex-col sm:flex-row gap-2 max-w-md">
		<div class="form-control flex-1">
			<input
				type="text"
				class="input input-bordered input-sm w-full"
				placeholder="sender@example.com or example.com"
				bind:value={newSenderInput}
				onkeydown={(e) => { if (e.key === 'Enter') handleAddRule(); }}
			/>
		</div>
		<select
			class="select select-bordered select-sm"
			bind:value={newAction}
			aria-label="Rule action"
		>
			<option value="ignore">Ignore</option>
			<option value="auto_approve">Auto-approve</option>
		</select>
		<button
			class="btn btn-primary btn-sm"
			onclick={handleAddRule}
			disabled={isAdding || !newSenderInput.trim()}
		>
			{#if isAdding}
				<span class="loading loading-spinner loading-xs"></span>
			{/if}
			Add rule
		</button>
	</div>
{/if}

<ConfirmModal
	open={showDeleteModal}
	title="Delete rule"
	description="Are you sure you want to delete the rule for {deleteTargetLabel}?"
	confirmText="Delete"
	confirmClass="btn-error"
	onconfirm={handleDeleteConfirm}
	oncancel={handleDeleteCancel}
/>
