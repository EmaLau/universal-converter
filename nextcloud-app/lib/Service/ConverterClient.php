<?php
declare(strict_types=1);

namespace OCA\Convertitore\Service;

use OCP\Files\File;
use OCP\Http\Client\IClientService;
use OCP\IAppConfig;
use OCP\ICache;
use OCP\ICacheFactory;
use Psr\Log\LoggerInterface;

/** Parla con il server Universal Converter (API descritta in server/converter/app.py). */
class ConverterClient {
	private ICache $cache;

	public function __construct(
		private IClientService $clientService,
		private IAppConfig $appConfig,
		ICacheFactory $cacheFactory,
		private LoggerInterface $logger,
	) {
		$this->cache = $cacheFactory->createDistributed('convertitore');
	}

	/** Indirizzo del server, impostato con: occ config:app:set convertitore converter_url --value=http://... */
	public function baseUrl(): string {
		return rtrim(trim($this->appConfig->getValueString('convertitore', 'converter_url', '')), '/');
	}

	private function url(string $path): string {
		$base = $this->baseUrl();
		if ($base === '') {
			throw new ConvertException('Indirizzo del convertitore non configurato (converter_url)');
		}
		return $base . $path;
	}

	private function opts(array $extra = []): array {
		// Di solito il server sta su un indirizzo privato: il client HTTP di Nextcloud li blocca se non lo si autorizza.
		return $extra + ['nextcloud' => ['allow_local_address' => true], 'timeout' => 30, 'http_errors' => false];
	}

	private static function detail(string $body, int $code): string {
		$d = json_decode($body, true);
		return is_array($d) && isset($d['detail']) && is_string($d['detail']) ? $d['detail'] : "HTTP $code";
	}

	/** @return array{inputs: array<string, list<string>>, categories: array<string, string>} */
	public function formats(): array {
		$cached = $this->cache->get('formats');
		if (is_array($cached)) {
			return $cached;
		}
		if ($this->baseUrl() === '') {
			return ['inputs' => [], 'categories' => []];  // non configurato: nessuna voce nel menu
		}
		try {
			$r = $this->clientService->newClient()->get($this->url('/api/formats'), $this->opts(['timeout' => 5]));
			$d = json_decode((string)$r->getBody(), true);
			if ($r->getStatusCode() === 200 && is_array($d) && isset($d['inputs'])) {
				$out = ['inputs' => $d['inputs'], 'categories' => $d['categories'] ?? []];
				$this->cache->set('formats', $out, 3600);
				return $out;
			}
		} catch (\Throwable $e) {
			$this->logger->warning('Convertitore non raggiungibile: ' . $e->getMessage(), ['app' => 'convertitore']);
		}
		$this->cache->set('formats', ['inputs' => [], 'categories' => []], 60);
		return ['inputs' => [], 'categories' => []];
	}

	/** Invia il file e restituisce l'id del lavoro. */
	public function submit(File $file, string $target): string {
		$fh = $file->fopen('r');
		if ($fh === false) {
			throw new ConvertException('Impossibile leggere il file');
		}
		try {
			$r = $this->clientService->newClient()->post($this->url('/api/jobs'), $this->opts([
				'timeout' => 3600,
				'multipart' => [
					['name' => 'target', 'contents' => $target],
					['name' => 'meta', 'contents' => 'nextcloud'],
					['name' => 'file', 'contents' => $fh, 'filename' => $file->getName()],
				],
			]));
		} catch (\Throwable $e) {
			throw new ConvertException('Convertitore non raggiungibile: ' . $e->getMessage());
		} finally {
			if (is_resource($fh)) {
				fclose($fh);
			}
		}
		$body = (string)$r->getBody();
		$d = json_decode($body, true);
		if ($r->getStatusCode() !== 201 || !is_array($d) || !isset($d['id'])) {
			throw new ConvertException(self::detail($body, $r->getStatusCode()));
		}
		return (string)$d['id'];
	}

	/** Stato del lavoro, oppure null se il convertitore non lo conosce (gia' cancellato o riavvio). */
	public function status(string $job): ?array {
		try {
			$r = $this->clientService->newClient()->get($this->url('/api/jobs/' . rawurlencode($job)), $this->opts());
		} catch (ConvertException $e) {
			throw $e;
		} catch (\Throwable $e) {
			throw new ConvertException('Convertitore non raggiungibile: ' . $e->getMessage());
		}
		if ($r->getStatusCode() === 404) {
			return null;
		}
		$d = json_decode((string)$r->getBody(), true);
		if ($r->getStatusCode() !== 200 || !is_array($d)) {
			throw new ConvertException('Risposta inattesa dal convertitore (HTTP ' . $r->getStatusCode() . ')');
		}
		return $d;
	}

	/** @return resource */
	public function download(string $job) {
		try {
			$r = $this->clientService->newClient()->get($this->url('/api/jobs/' . rawurlencode($job) . '/download'),
				$this->opts(['stream' => true, 'timeout' => 3600]));
		} catch (ConvertException $e) {
			throw $e;
		} catch (\Throwable $e) {
			throw new ConvertException('Convertitore non raggiungibile: ' . $e->getMessage());
		}
		if ($r->getStatusCode() !== 200) {
			throw new ConvertException('Download del risultato fallito (HTTP ' . $r->getStatusCode() . ')');
		}
		$body = $r->getBody();
		if (!is_resource($body)) {
			$tmp = fopen('php://temp', 'w+');
			fwrite($tmp, (string)$body);
			rewind($tmp);
			return $tmp;
		}
		return $body;
	}

	public function delete(string $job): void {
		try {
			$this->clientService->newClient()->delete($this->url('/api/jobs/' . rawurlencode($job)), $this->opts());
		} catch (\Throwable $e) {
			// il convertitore cancella comunque i lavori vecchi da solo
		}
	}
}
