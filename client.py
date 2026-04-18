"""HTTP client for Mattilsynet smilefjes CSV endpoints.

Two cumulative CSV dumps published daily at::

    https://matnyttig.mattilsynet.no/smilefjes/tilsyn.csv
    https://matnyttig.mattilsynet.no/smilefjes/vurderinger.csv

No authentication. CC BY 4.0. UTF-8 with BOM, semicolon-delimited.
Each fetch returns the full cumulative dataset (not incremental); the
parser handles CDC against prior state.

``dato`` fields in both CSVs use ``ddmmyyyy`` format (no separators).
"""

import requests
import time


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

    def __init__(self, timeout=120):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers["Accept"] = "text/csv, */*"
        self._session.headers["User-Agent"] = "smilefjes-collector/1.0 (Sondre Skarsten)"
        self._request_count = 0

    def fetch(self, dataset):
        """Fetch one dataset as raw bytes.

        Parameters
        ----------
        dataset : str
            Either ``"tilsyn"`` or ``"vurderinger"``.

        Returns
        -------
        bytes
            Raw CSV bytes with UTF-8 BOM stripped.

        Raises
        ------
        requests.HTTPError
            On any non-200 response.
        """
        url = f"{BASE}/{dataset}.csv"
        self._request_count += 1
        r = self._session.get(url, timeout=self.timeout)
        r.raise_for_status()
        body = r.content
        if body.startswith(b"\xef\xbb\xbf"):
            body = body[3:]
        return body
