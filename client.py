"""HTTP client for Mattilsynet smilefjes CSV endpoints.

Two cumulative CSV dumps published daily at::

    https://matnyttig.mattilsynet.no/smilefjes/tilsyn.csv
    https://matnyttig.mattilsynet.no/smilefjes/vurderinger.csv

No authentication. CC BY 4.0. UTF-8, semicolon-delimited. A publisher BOM,
when present, is preserved. Each fetch returns the full cumulative dataset.

``dato`` fields in both CSVs use ``ddmmyyyy`` format (no separators).
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE = "https://matnyttig.mattilsynet.no/smilefjes"


class SmilefjesClient:
    """HTTP client for Mattilsynet smilefjes CSV endpoints.

    Parameters
    ----------
    timeout : int
        Per-request timeout in seconds. Default ``120``.

    Attributes
    ----------
    _request_count : int
        Running count of HTTP requests issued in this session.
    """

    def __init__(self, timeout: int = 120):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers["Accept"] = "text/csv, */*"
        self._session.headers["User-Agent"] = "smilefjes-collector/1.0 (Sondre Skarsten)"
        retry = Retry(
            total=5,
            backoff_factor=0.2,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        self._request_count = 0

    def fetch(self, dataset: str) -> bytes:
        """Fetch one dataset as raw bytes.

        Parameters
        ----------
        dataset : str
            Either ``"tilsyn"`` or ``"vurderinger"``.

        Returns
        -------
        bytes
            Exact raw CSV bytes returned by the publisher.

        Raises
        ------
        requests.HTTPError
            On any non-200 response.
        """
        url = f"{BASE}/{dataset}.csv"
        self._request_count += 1
        r = self._session.get(url, timeout=self.timeout)
        r.raise_for_status()
        return r.content
