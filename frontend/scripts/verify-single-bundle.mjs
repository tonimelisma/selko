import { readFile, readdir } from 'node:fs/promises';
import { relative, resolve } from 'node:path';

const buildDirectory = resolve('build');
const immutableDirectory = resolve(buildDirectory, '_app', 'immutable');

/** @param {string} directory */
async function listJavaScriptFiles(directory) {
	const entries = await readdir(directory, { withFileTypes: true });
	const files = await Promise.all(
		entries.map((entry) => {
			const path = resolve(directory, entry.name);
			return entry.isDirectory() ? listJavaScriptFiles(path) : path.endsWith('.js') ? [path] : [];
		})
	);

	return files.flat();
}

const javascriptFiles = await listJavaScriptFiles(immutableDirectory);

if (javascriptFiles.length !== 1) {
	const emittedFiles = javascriptFiles.map((file) => relative(buildDirectory, file)).join('\n  ');
	throw new Error(
		`Expected one production JavaScript bundle, found ${javascriptFiles.length}:\n  ${emittedFiles}`
	);
}

console.log(`Verified single production JavaScript bundle: ${relative(buildDirectory, javascriptFiles[0])}`);

const html = await readFile(resolve(buildDirectory, 'index.html'), 'utf8');

if (html.includes('rel="modulepreload"')) {
	throw new Error('Production HTML must not use modulepreload because Safari can cancel those requests');
}

if (!html.includes('rel="preload"') || !html.includes('as="script"')) {
	throw new Error('Production HTML must preload the single bundle as a classic script resource');
}

console.log('Verified Safari-compatible JavaScript preload strategy');
