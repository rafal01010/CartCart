import { buildRunEventsUrl } from './client.js';
import type { RunEvent, RunId, SessionId } from './types.js';

type EventSourceHandler = (event: MessageEvent) => void;
type EventSourceErrorHandler = (event: Event) => void;

interface EventSourceLike {
	addEventListener(type: 'run_event', listener: EventSourceHandler): void;
	addEventListener(type: 'error', listener: EventSourceErrorHandler): void;
	close(): void;
}

type EventSourceConstructor = new (url: string) => EventSourceLike;

export interface RunEventSubscriptionOptions {
	baseUrl?: string;
	eventSource?: EventSourceConstructor;
	onEvent: (event: RunEvent) => void;
	onError?: (event: Event) => void;
}

export interface RunEventSubscription {
	url: string;
	close: () => void;
}

export function subscribeToRunEvents(
	params: { sessionId: SessionId; runId: RunId },
	options: RunEventSubscriptionOptions,
): RunEventSubscription {
	const url = buildRunEventsUrl(params.sessionId, params.runId, options.baseUrl);
	const EventSourceImpl = options.eventSource ?? globalThis.EventSource;
	if (!EventSourceImpl) {
		throw new Error('EventSource is not available in this environment.');
	}

	const source = new EventSourceImpl(url);
	source.addEventListener('run_event', (event) => {
		options.onEvent(JSON.parse(event.data) as RunEvent);
	});
	source.addEventListener('error', (event) => {
		options.onError?.(event);
	});

	return {
		url,
		close: () => source.close(),
	};
}
