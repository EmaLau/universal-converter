<?php
declare(strict_types=1);

namespace OCA\Convertitore\Service;

use OCA\Convertitore\BackgroundJob\FinalizeJob;
use OCP\BackgroundJob\IJobList;
use OCP\Files\File;
use OCP\Files\Folder;
use OCP\Files\IRootFolder;
use OCP\ICache;
use OCP\ICacheFactory;
use Psr\Log\LoggerInterface;

/**
 * Avvia le conversioni e salva il risultato accanto all'originale.
 * Il salvataggio lo fa chi arriva prima: il browser che interroga lo stato oppure FinalizeJob (cron),
 * cosi' il file arriva anche se l'utente chiude la pagina.
 */
class Jobs {
	private const TTL = 172800;
	private ICache $cache;

	public function __construct(
		private ConverterClient $client,
		private IRootFolder $rootFolder,
		private IJobList $jobList,
		ICacheFactory $cacheFactory,
		private LoggerInterface $logger,
	) {
		$this->cache = $cacheFactory->createDistributed('convertitore-jobs');
	}

	public function start(string $uid, int $fileId, string $target): string {
		$node = $this->rootFolder->getUserFolder($uid)->getFirstNodeById($fileId);
		if (!$node instanceof File || !$node->isReadable()) {
			throw new ConvertException('File non trovato');
		}
		$job = $this->client->submit($node, $target);
		$this->cache->set("job:$job", ['uid' => $uid, 'fileId' => $fileId, 'target' => $target, 'state' => 'pending'], self::TTL);
		$this->jobList->add(FinalizeJob::class, ['job' => $job, 'uid' => $uid, 'ts' => time()]);
		return $job;
	}

	/** Stato per il browser; se il convertitore ha finito, salva il file. */
	public function poll(string $uid, string $job): array {
		$info = $this->cache->get("job:$job");
		if (!is_array($info) || $info['uid'] !== $uid) {
			throw new ConvertException('Conversione sconosciuta o scaduta');
		}
		if (isset($info['result'])) {
			return $info['result'];
		}
		$st = $this->client->status($job);
		if ($st === null) {
			$info = $this->cache->get("job:$job");  // forse l'ha appena salvata qualcun altro
			if (is_array($info) && isset($info['result'])) {
				return $info['result'];
			}
			return $this->finish($job, $info ?: [], ['state' => 'error', 'error' => 'Il convertitore ha perso il lavoro (riavviato?)']);
		}
		if ($st['state'] === 'error') {
			$this->client->delete($job);
			return $this->finish($job, $info, ['state' => 'error', 'error' => (string)($st['error'] ?? 'errore')]);
		}
		if ($st['state'] !== 'done') {
			return ['state' => $st['state'], 'progress' => $st['progress'] ?? null, 'step' => $st['step'] ?? '', 'position' => $st['position'] ?? null];
		}
		return $this->save($job, $st);
	}

	private function finish(string $job, array $info, array $result): array {
		$this->cache->set("job:$job", $info + ['result' => $result], 86400);
		return $result;
	}

	private function save(string $job, array $st): array {
		if (!$this->cache->add("lock:$job", 1, 900)) {
			return ['state' => 'running', 'step' => 'Salvataggio…', 'progress' => 1];
		}
		try {
			$info = $this->cache->get("job:$job");
			if (isset($info['result'])) {
				return $info['result'];
			}
			$userFolder = $this->rootFolder->getUserFolder($info['uid']);
			$src = $userFolder->getFirstNodeById((int)$info['fileId']);
			$parent = $src?->getParent();
			$note = '';
			if (!$parent instanceof Folder || !$parent->isCreatable()) {
				$parent = $userFolder;  // cartella condivisa in sola lettura: salvo nella radice
				$note = 'cartella di origine non scrivibile, salvato nella cartella principale';
			}
			$name = $parent->getNonExistingName((string)$st['out_name']);
			$stream = $this->client->download($job);
			try {
				$new = $parent->newFile($name, $stream);
			} finally {
				if (is_resource($stream)) {
					fclose($stream);
				}
			}
			$this->client->delete($job);
			return $this->finish($job, $info, [
				'state' => 'done', 'fileId' => $new->getId(), 'name' => $name, 'parentId' => $parent->getId(),
				'path' => $userFolder->getRelativePath($new->getPath()), 'size' => $new->getSize(),
				'mime' => $new->getMimetype(), 'mtime' => $new->getMTime(), 'note' => $note,
			]);
		} catch (\Throwable $e) {
			$this->logger->error('Convertitore: salvataggio fallito: ' . $e->getMessage(), ['app' => 'convertitore', 'exception' => $e]);
			return $this->finish($job, $info ?? [], ['state' => 'error', 'error' => 'Salvataggio fallito: ' . $e->getMessage()]);
		} finally {
			$this->cache->remove("lock:$job");
		}
	}
}
