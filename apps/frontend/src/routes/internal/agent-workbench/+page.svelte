<script lang="ts">
	import { onMount } from 'svelte';
	import AlertTriangle from '@lucide/svelte/icons/alert-triangle';
	import Play from '@lucide/svelte/icons/play';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import { buildApiUrl } from '$lib/api/config.js';
	import { Button } from '$lib/components/ui/button/index.js';

	type WorkbenchMode = 'fixture' | 'mock' | 'live';
	type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

	interface WorkbenchScenario {
		name: string;
		description: string;
		input: Record<string, JsonValue>;
		boundary: boolean;
	}

	interface WorkbenchAgent {
		agent_name: string;
		kind: string;
		invocation_mode: string;
		input_schema: string;
		output_schema: string;
		modes: WorkbenchMode[];
		scenarios: WorkbenchScenario[];
	}

	interface WorkbenchCatalog {
		enabled: boolean;
		environment: string;
		live_agents_enabled: boolean;
		live_mode_notice: string;
		agents: WorkbenchAgent[];
	}

	interface WorkbenchResult {
		agent_name: string;
		scenario_name: string;
		mode: WorkbenchMode;
		input_schema: string;
		output_schema: string;
		input: Record<string, JsonValue>;
		output?: JsonValue;
		allowed_tool_activity: JsonValue[];
		fallback: { used: boolean; reason?: string | null };
		error?: string | null;
		trace_id: string;
		usage?: JsonValue;
		model: string;
		elapsed_ms: number;
		live_mode_notice?: string | null;
	}

	interface ErrorEnvelope {
		error?: {
			code?: string;
			message?: string;
			details?: JsonValue;
		};
	}

	let catalog = $state<WorkbenchCatalog | null>(null);
	let selectedAgentName = $state('');
	let selectedScenarioName = $state('');
	let selectedMode = $state<WorkbenchMode>('fixture');
	let inputJson = $state('');
	let result = $state<WorkbenchResult | null>(null);
	let errorMessage = $state<string | null>(null);
	let isLoading = $state(false);
	let isRunning = $state(false);

	const selectedAgent = $derived(
		catalog?.agents.find((agent) => agent.agent_name === selectedAgentName) ?? null,
	);
	const selectedScenario = $derived(
		selectedAgent?.scenarios.find((scenario) => scenario.name === selectedScenarioName) ?? null,
	);
	const modeOptions = $derived(selectedAgent?.modes ?? ['fixture', 'mock']);

	onMount(() => {
		void loadCatalog();
	});

	async function loadCatalog() {
		isLoading = true;
		errorMessage = null;
		result = null;
		try {
			const response = await fetch(buildApiUrl('/internal/agent-workbench'), {
				headers: { Accept: 'application/json' },
			});
			if (!response.ok) {
				throw new Error(await readErrorMessage(response));
			}
			catalog = (await response.json()) as WorkbenchCatalog;
			const firstAgent = catalog.agents[0] ?? null;
			if (firstAgent) {
				selectAgent(firstAgent.agent_name);
			}
		} catch (error) {
			errorMessage = error instanceof Error ? error.message : 'Workbench is unavailable.';
		} finally {
			isLoading = false;
		}
	}

	function selectAgent(agentName: string) {
		selectedAgentName = agentName;
		const agent = catalog?.agents.find((item) => item.agent_name === agentName) ?? null;
		const scenario = agent?.scenarios[0] ?? null;
		selectedScenarioName = scenario?.name ?? '';
		selectedMode = agent?.modes.includes(selectedMode) ? selectedMode : 'fixture';
		inputJson = scenario ? formatJson(scenario.input) : '';
		result = null;
		errorMessage = null;
	}

	function selectScenario(scenarioName: string) {
		selectedScenarioName = scenarioName;
		const scenario = selectedAgent?.scenarios.find((item) => item.name === scenarioName) ?? null;
		inputJson = scenario ? formatJson(scenario.input) : '';
		result = null;
		errorMessage = null;
	}

	function selectAgentFromEvent(event: Event) {
		selectAgent((event.currentTarget as HTMLSelectElement).value);
	}

	function selectScenarioFromEvent(event: Event) {
		selectScenario((event.currentTarget as HTMLSelectElement).value);
	}

	async function runWorkbench() {
		if (!selectedAgent || !selectedScenario || isRunning) return;
		isRunning = true;
		errorMessage = null;
		result = null;
		try {
			const parsedInput = JSON.parse(inputJson) as unknown;
			if (!parsedInput || typeof parsedInput !== 'object' || Array.isArray(parsedInput)) {
				throw new Error('Input must be a JSON object.');
			}
			const response = await fetch(buildApiUrl('/internal/agent-workbench/runs'), {
				method: 'POST',
				headers: {
					Accept: 'application/json',
					'Content-Type': 'application/json',
				},
				body: JSON.stringify({
					agent_name: selectedAgent.agent_name,
					scenario_name: selectedScenario.name,
					mode: selectedMode,
					input: parsedInput,
				}),
			});
			if (!response.ok) {
				throw new Error(await readErrorMessage(response));
			}
			result = (await response.json()) as WorkbenchResult;
		} catch (error) {
			errorMessage = error instanceof Error ? error.message : 'Workbench run failed.';
		} finally {
			isRunning = false;
		}
	}

	function formatJson(value: unknown) {
		return JSON.stringify(value, null, 2);
	}

	async function readErrorMessage(response: Response) {
		try {
			const envelope = (await response.json()) as ErrorEnvelope;
			return envelope.error?.message ?? response.statusText;
		} catch {
			return response.statusText || `HTTP ${response.status}`;
		}
	}
</script>

<svelte:head>
	<title>Agent Workbench · CartCart</title>
</svelte:head>

<main class="min-h-screen bg-background px-4 py-6 text-foreground sm:px-6 lg:px-8">
	<div class="mx-auto flex w-full max-w-[1200px] flex-col gap-5">
		<header class="flex flex-col gap-3 border-b border-border pb-5 md:flex-row md:items-end md:justify-between">
			<div>
				<p class="font-mono text-xs text-muted-foreground">LOCAL INTERNAL</p>
				<h1 class="mt-1 text-3xl font-[510] tracking-[-0.012em]">Agent Workbench</h1>
				<p class="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
					Isolated typed-agent scenarios for fixture, mock, and explicitly enabled live checks.
				</p>
			</div>
			<Button type="button" variant="outline" onclick={loadCatalog} disabled={isLoading}>
				<RefreshCw class="size-4" aria-hidden="true" />
				Reload
			</Button>
		</header>

		{#if errorMessage}
			<section class="flex items-start gap-3 rounded-md border border-destructive/60 bg-destructive/10 p-4 text-sm text-foreground">
				<AlertTriangle class="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden="true" />
				<p>{errorMessage}</p>
			</section>
		{/if}

		{#if catalog}
			<section class="grid gap-4 lg:grid-cols-[360px_1fr]">
				<div class="flex flex-col gap-4">
					<label class="flex flex-col gap-2 text-sm">
						<span class="text-muted-foreground">Agent</span>
						<select
							class="h-10 rounded-md border border-border bg-input px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
							bind:value={selectedAgentName}
							onchange={selectAgentFromEvent}
						>
							{#each catalog.agents as agent}
								<option value={agent.agent_name}>{agent.agent_name}</option>
							{/each}
						</select>
					</label>

					<label class="flex flex-col gap-2 text-sm">
						<span class="text-muted-foreground">Scenario</span>
						<select
							class="h-10 rounded-md border border-border bg-input px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
							bind:value={selectedScenarioName}
							onchange={selectScenarioFromEvent}
						>
							{#each selectedAgent?.scenarios ?? [] as scenario}
								<option value={scenario.name}>{scenario.name}</option>
							{/each}
						</select>
					</label>

					<label class="flex flex-col gap-2 text-sm">
						<span class="text-muted-foreground">Mode</span>
						<select
							class="h-10 rounded-md border border-border bg-input px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
							bind:value={selectedMode}
						>
							{#each modeOptions as mode}
								<option value={mode}>{mode}</option>
							{/each}
						</select>
					</label>

					{#if selectedAgent}
						<div class="rounded-md border border-border bg-card p-4 text-sm leading-6 text-muted-foreground shadow-subtle">
							<p><span class="text-foreground">Kind:</span> {selectedAgent.kind}</p>
							<p><span class="text-foreground">Input:</span> {selectedAgent.input_schema}</p>
							<p><span class="text-foreground">Output:</span> {selectedAgent.output_schema}</p>
							<p><span class="text-foreground">Invocation:</span> {selectedAgent.invocation_mode}</p>
						</div>
					{/if}

					{#if selectedScenario}
						<div class="rounded-md border border-border bg-card p-4 text-sm leading-6 text-muted-foreground shadow-subtle">
							<p class="text-foreground">{selectedScenario.description}</p>
							{#if selectedScenario.boundary}
								<p class="mt-2 font-mono text-xs text-warning-foreground">BOUNDARY / FAILURE</p>
							{/if}
						</div>
					{/if}
				</div>

				<div class="flex min-w-0 flex-col gap-4">
					<label class="flex flex-col gap-2 text-sm">
						<span class="text-muted-foreground">Input JSON</span>
						<textarea
							class="min-h-[420px] resize-y rounded-md border border-border bg-input p-3 font-mono text-xs leading-5 text-foreground outline-none focus:ring-2 focus:ring-ring"
							bind:value={inputJson}
							spellcheck="false"
						></textarea>
					</label>

					<div class="flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
						{#if selectedMode === 'live'}
							<p class="text-sm text-warning-foreground">{catalog.live_mode_notice}</p>
						{:else}
							<p class="text-sm text-muted-foreground">
								Fixture and mock runs do not make provider or model calls.
							</p>
						{/if}
						<Button type="button" onclick={runWorkbench} disabled={isRunning || !selectedAgent}>
							<Play class="size-4" aria-hidden="true" />
							Run
						</Button>
					</div>
				</div>
			</section>
		{:else if isLoading}
			<p class="text-sm text-muted-foreground">Loading workbench catalog...</p>
		{/if}

		{#if result}
			<section class="grid gap-4 lg:grid-cols-2">
				<div class="rounded-md border border-border bg-card p-4 shadow-subtle">
					<h2 class="text-sm font-[510]">Run</h2>
					<dl class="mt-3 grid gap-2 text-sm text-muted-foreground sm:grid-cols-2">
						<div><dt>Trace</dt><dd class="font-mono text-foreground">{result.trace_id}</dd></div>
						<div><dt>Model</dt><dd class="font-mono text-foreground">{result.model}</dd></div>
						<div><dt>Mode</dt><dd class="font-mono text-foreground">{result.mode}</dd></div>
						<div><dt>Timing</dt><dd class="font-mono text-foreground">{result.elapsed_ms} ms</dd></div>
					</dl>
				</div>

				<div class="rounded-md border border-border bg-card p-4 shadow-subtle">
					<h2 class="text-sm font-[510]">Activity</h2>
					<pre class="mt-3 max-h-56 overflow-auto rounded-md bg-background p-3 font-mono text-xs leading-5 text-muted-foreground">{formatJson({
							tools: result.allowed_tool_activity,
							fallback: result.fallback,
							error: result.error,
							usage: result.usage ?? null,
						})}</pre>
				</div>

				<div class="rounded-md border border-border bg-card p-4 shadow-subtle">
					<h2 class="text-sm font-[510]">Validated Input</h2>
					<pre class="mt-3 max-h-[520px] overflow-auto rounded-md bg-background p-3 font-mono text-xs leading-5 text-muted-foreground">{formatJson(result.input)}</pre>
				</div>

				<div class="rounded-md border border-border bg-card p-4 shadow-subtle">
					<h2 class="text-sm font-[510]">Structured Output</h2>
					<pre class="mt-3 max-h-[520px] overflow-auto rounded-md bg-background p-3 font-mono text-xs leading-5 text-muted-foreground">{formatJson(result.output ?? null)}</pre>
				</div>
			</section>
		{/if}
	</div>
</main>
