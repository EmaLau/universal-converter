<?php
declare(strict_types=1);

namespace OCA\Convertitore\Listener;

use OCA\Convertitore\AppInfo\Application;
use OCA\Convertitore\Service\ConverterClient;
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
		Util::addScript(Application::APP_ID, 'convertitore');
	}
}
