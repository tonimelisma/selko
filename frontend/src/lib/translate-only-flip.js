import { cubicOut } from 'svelte/easing';

/**
 * FLIP animation that moves an item without scaling its contents.
 * Svelte's built-in `flip` also interpolates width and height, which makes
 * unchanged Review cards visibly stretch during background refreshes.
 *
 * @param {HTMLElement} node
 * @param {{from: DOMRect, to: DOMRect}} bounds
 * @param {{duration?: number}} [params]
 */
export function translateOnlyFlip(node, { from, to }, params = {}) {
	const duration = params.duration ?? 180;
	const dx = from.left - to.left;
	const dy = from.top - to.top;
	const reducedMotion =
		typeof window !== 'undefined' &&
		window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

	if (reducedMotion || (dx === 0 && dy === 0)) {
		return { duration: 0 };
	}

	const transform = getComputedStyle(node).transform;
	const baseTransform = transform === 'none' ? '' : `${transform} `;
	return {
		duration,
		easing: cubicOut,
		css: (/** @type {number} */ _t, /** @type {number} */ u) =>
			`transform: ${baseTransform}translate3d(${u * dx}px, ${u * dy}px, 0);`
	};
}
