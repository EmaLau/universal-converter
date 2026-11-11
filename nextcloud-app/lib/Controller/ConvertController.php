<?php
declare(strict_types=1);

namespace OCA\Convertitore\Controller;

use OCA\Convertitore\Service\ConvertException;
use OCA\Convertitore\Service\Jobs;
use OCP\AppFramework\Controller;
use OCP\AppFramework\Http;
use OCP\AppFramework\Http\Attribute\FrontpageRoute;
use OCP\AppFramework\Http\Attribute\NoAdminRequired;
use OCP\AppFramework\Http\JSONResponse;
use OCP\IRequest;
use OCP\IUserSession;

class ConvertController extends Controller {
	public function __construct(
		IRequest $request,
		private Jobs $jobs,
		private IUserSession $userSession,
	) {
		parent::__construct('convertitore', $request);
	}

	private function uid(): string {
		return $this->userSession->getUser()?->getUID() ?? throw new ConvertException('Non autenticato');
	}

	#[NoAdminRequired]
	#[FrontpageRoute(verb: 'POST', url: '/convert')]
	public function convert(int $fileId, string $target): JSONResponse {
		try {
			return new JSONResponse(['job' => $this->jobs->start($this->uid(), $fileId, strtolower($target))]);
		} catch (ConvertException $e) {
			return new JSONResponse(['error' => $e->getMessage()], Http::STATUS_BAD_REQUEST);
		}
	}

	#[NoAdminRequired]
	#[FrontpageRoute(verb: 'GET', url: '/status/{job}', requirements: ['job' => '[0-9a-f]{32}'])]
	public function status(string $job): JSONResponse {
		try {
			return new JSONResponse($this->jobs->poll($this->uid(), $job));
		} catch (ConvertException $e) {
			return new JSONResponse(['state' => 'error', 'error' => $e->getMessage()], Http::STATUS_NOT_FOUND);
		}
	}
}
