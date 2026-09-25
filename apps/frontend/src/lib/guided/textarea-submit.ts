export interface TextareaSubmitOptions {
	disabled: boolean;
	submit: (value: string) => void;
}

export function submitTextareaOnEnter(
	textarea: HTMLTextAreaElement,
	initialOptions: TextareaSubmitOptions,
) {
	let options = initialOptions;

	function handleKeydown(event: KeyboardEvent) {
		if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
		event.preventDefault();
		if (!options.disabled && textarea.value.trim()) options.submit(textarea.value);
	}

	textarea.addEventListener('keydown', handleKeydown);
	return {
		update(nextOptions: TextareaSubmitOptions) {
			options = nextOptions;
		},
		destroy() {
			textarea.removeEventListener('keydown', handleKeydown);
		},
	};
}
