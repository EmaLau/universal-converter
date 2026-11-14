<?php
declare(strict_types=1);

namespace OCA\UniversalConverter\Listener;

use OCA\UniversalConverter\AppInfo\Application;
use OCA\UniversalConverter\Service\ConverterClient;
use OCA\Files\Event\LoadAdditionalScriptsEvent;
use OCP\AppFramework\Services\IInitialState;
use OCP\EventDispatcher\Event;
use OCP\EventDispatcher\IEventListener;
use OCP\Util;

/** @template-implements IEventListener<LoadAdditionalScriptsEvent> */
class LoadScriptsListener implements IEventListener {
	public function __construct(
		private ConverterClient $client,
		private IInitialState $initialState,
	) {
	}

	public function handle(Event $event): void {
		if (!$event instanceof LoadAdditionalScriptsEvent) {
			return;
		}
		// La tabella dei formati arriva insieme alla pagina: il JS registra le azioni subito, senza fetch.
		$this->initialState->provideLazyInitialState('formats', fn () => $this->client->formats());
		Util::addTranslations(Application::APP_ID);
		Util::addScript(Application::APP_ID, 'universal_converter');
	}
}
