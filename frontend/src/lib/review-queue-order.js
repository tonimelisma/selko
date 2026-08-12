/**
 * Review queue stable ordering — session-persistent ranks.
 * Implements docs/specs/review-queue-integrity.md §5.1.
 *
 * One LaneOrder per lane (pending_review, pending_change). Ranks increase
 * monotonically for the mounted session, never renumber after removal, and
 * retain removed event ranks for Undo.
 *
 * Server decides membership; client decides where already-seen rows remain.
 */

/**
 * @typedef {{
 *   senderRank: Map<string, number>,
 *   eventRank: Map<string, number>,
 *   nextSenderRank: number,
 *   nextEventRank: number
 * }} LaneOrder
 */

/**
 * Create an empty lane order.
 * @returns {LaneOrder}
 */
export function createLaneOrder() {
	return {
		senderRank: new Map(),
		eventRank: new Map(),
		nextSenderRank: 0,
		nextEventRank: 0
	};
}

/**
 * Seed a lane order from the first successful server snapshot.
 * Order is server order (start_datetime ASC as returned); ties use array index
 * only during seeding — never Date comparison during reconciliation.
 *
 * @param {any[]} events
 * @param {(event: any) => {senderKey: string}} senderForEvent
 * @returns {LaneOrder}
 */
export function seedLaneOrder(events, senderForEvent) {
	const order = createLaneOrder();
	for (const event of events) {
		const { senderKey } = senderForEvent(event);
		if (!order.senderRank.has(senderKey)) {
			order.senderRank.set(senderKey, order.nextSenderRank++);
		}
		if (!order.eventRank.has(event.id)) {
			order.eventRank.set(event.id, order.nextEventRank++);
		}
	}
	return order;
}

/**
 * Reconcile an existing lane order with a fresh server snapshot.
 * Rules (§5.1):
 * 1. ID already in eventRank keeps its rank.
 * 2. Sender already in senderRank keeps group rank even if earliest event disappeared.
 * 3. New card for existing sender appends after that sender's known cards (handled by sortLaneEvents).
 * 4. Previously unseen sender appends after all known groups.
 * 5. Card moving between lanes appends in destination lane (caller seeds dest if needed).
 * 6. Missing cards leave membership but remain in rank maps for Undo.
 * 7. Ties use server array index only during initial seeding; never Date during reconciliation.
 *
 * @param {LaneOrder} order
 * @param {any[]} previousEvents - events previously in this lane (membership before refresh)
 * @param {any[]} loadedEvents - fresh server snapshot for this lane
 * @param {(event: any) => {senderKey: string}} senderForEvent
 * @returns {LaneOrder} mutated order (same reference for svelte reactivity via new Map assignment)
 */
export function reconcileLaneOrder(order, previousEvents, loadedEvents, senderForEvent) {
	// For each loaded event, ensure sender and event have ranks; new senders append.
	for (const event of loadedEvents) {
		const { senderKey } = senderForEvent(event);
		if (!order.senderRank.has(senderKey)) {
			order.senderRank.set(senderKey, order.nextSenderRank++);
		}
		if (!order.eventRank.has(event.id)) {
			order.eventRank.set(event.id, order.nextEventRank++);
		}
	}
	// Do not delete ranks for missing cards — retain for Undo.
	return order;
}

/**
 * Sort events according to stable lane order.
 * 1. Group sort by senderRank (existing groups keep position; new senders at end).
 * 2. Within each group, sort by eventRank.
 *
 * This helper returns a new array in display order; grouping is still done by
 * caller via groupBySender if needed, but this provides the canonical card order.
 *
 * @param {any[]} events
 * @param {LaneOrder} order
 * @param {(event: any) => {senderKey: string}} senderForEvent
 * @returns {any[]} sorted copy
 */
export function sortLaneEvents(events, order, senderForEvent) {
	return [...events].sort((a, b) => {
		const aSender = senderForEvent(a).senderKey;
		const bSender = senderForEvent(b).senderKey;
		const aSenderRank = order.senderRank.get(aSender);
		const bSenderRank = order.senderRank.get(bSender);
		const aSR = aSenderRank ?? Number.MAX_SAFE_INTEGER;
		const bSR = bSenderRank ?? Number.MAX_SAFE_INTEGER;
		if (aSR !== bSR) return aSR - bSR;
		const aER = order.eventRank.get(a.id) ?? Number.MAX_SAFE_INTEGER;
		const bER = order.eventRank.get(b.id) ?? Number.MAX_SAFE_INTEGER;
		return aER - bER;
	});
}
