<?php
declare(strict_types=1);

namespace OCA\Convertitore\BackgroundJob;

use OCA\Convertitore\Service\Jobs;
use OCP\AppFramework\Utility\ITimeFactory;
use OCP\BackgroundJob\IJobList;
use OCP\BackgroundJob\QueuedJob;

/** Salva il risultato se il browser non lo ha fatto (pagina chiusa). Si riaccoda finche' il lavoro e' in corso. */
class FinalizeJob extends QueuedJob {
	public function __construct(
		ITimeFactory $time,
		private Jobs $jobs,
		private IJobList $jobList,
	) {
		parent::__construct($time);
	}

	protected function run($argument): void {
		try {
			$r = $this->jobs->poll((string)$argument['uid'], (string)$argument['job']);
		} catch (\Throwable $e) {
			return;  // sconosciuto/scaduto: niente da fare
		}
		if (in_array($r['state'], ['queued', 'running'], true) && time() - (int)$argument['ts'] < 86400) {
			$this->jobList->add(self::class, $argument);
		}
	}
}
