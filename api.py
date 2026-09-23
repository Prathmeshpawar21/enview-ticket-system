import os
import time
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()


class FieldServeAPIError(Exception):
    """Raised when the FieldServe API returns an unexpected error."""


class FieldServeAPI:
    """Client for the FieldServe helpdesk API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("FIELDOPS_BASE_URL")
        ).rstrip("/")

        self.api_key = api_key or os.getenv("FIELDOPS_API_KEY")

        if not self.base_url:
            raise ValueError(
                "FIELDOPS_BASE_URL is not configured."
            )

        if not self.api_key:
            raise ValueError(
                "FIELDOPS_API_KEY is not configured."
            )

        self.timeout = timeout

        self.session = requests.Session()

        # Assignment specifies API key as the Basic Auth username
        # and any password.
        self.session.auth = (self.api_key, "x")

        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def _url(self, path: str) -> str:
        """Build a full API URL."""
        return f"{self.base_url}/{path.lstrip('/')}"

    def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> requests.Response:
        """
        Make an API request with basic retry handling.

        The FieldServe API has a rate limit of 60 requests/minute
        and may return HTTP 429 with Retry-After.
        """

        url = self._url(path)

        max_retries = 5

        for attempt in range(max_retries + 1):
            response = self.session.request(
                method=method,
                url=url,
                timeout=self.timeout,
                **kwargs,
            )

            if response.status_code != 429:
                return response

            if attempt >= max_retries:
                break

            retry_after = response.headers.get("Retry-After")

            try:
                wait_seconds = float(retry_after)
            except (TypeError, ValueError):
                wait_seconds = min(2 ** attempt, 30)

            time.sleep(max(wait_seconds, 0))

        raise FieldServeAPIError(
            f"Rate limit exceeded after retries: "
            f"{method} {url}"
        )

    def _json_request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Any:
        """Make a request and return decoded JSON."""
        response = self._request(
            method,
            path,
            **kwargs,
        )

        if not response.ok:
            raise FieldServeAPIError(
                self._format_error(response)
            )

        try:
            return response.json()
        except ValueError as exc:
            raise FieldServeAPIError(
                f"Invalid JSON response from "
                f"{method} {response.url}"
            ) from exc

    @staticmethod
    def _format_error(
        response: requests.Response,
    ) -> str:
        """Create a useful API error message."""
        message = (
            f"FieldServe API error "
            f"{response.status_code}: "
            f"{response.request.method} "
            f"{response.url}"
        )

        try:
            payload = response.json()
            if payload:
                message += f" - {payload}"
        except ValueError:
            if response.text:
                message += f" - {response.text[:500]}"

        return message

    def get_agents(self) -> List[Dict[str, Any]]:
        """Return the complete agent roster."""
        data = self._json_request(
            "GET",
            "/api/v2/agents",
        )

        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            for key in ("agents", "data", "results"):
                value = data.get(key)
                if isinstance(value, list):
                    return value

        raise FieldServeAPIError(
            "Unexpected response format from /api/v2/agents"
        )

    def get_ticket(
        self,
        ticket_id: int,
    ) -> Dict[str, Any]:
        """Return one ticket by ID."""
        data = self._json_request(
            "GET",
            f"/api/v2/tickets/{ticket_id}",
        )

        if not isinstance(data, dict):
            raise FieldServeAPIError(
                f"Unexpected ticket response for {ticket_id}"
            )

        return data

    def update_ticket(
        self,
        ticket_id: int,
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Partially update a ticket.

        Only writable fields should be passed by callers.
        """
        if not updates:
            return self.get_ticket(ticket_id)

        data = self._json_request(
            "PUT",
            f"/api/v2/tickets/{ticket_id}",
            json=updates,
        )

        if not isinstance(data, dict):
            raise FieldServeAPIError(
                f"Unexpected update response for {ticket_id}"
            )

        return data

    def list_tickets_page(
        self,
        page: int = 1,
        per_page: int = 50,
        updated_since: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch one page of tickets.

        The API supports:
        - page
        - per_page (maximum 50)
        - updated_since
        """
        if page < 1:
            raise ValueError("page must be >= 1")

        if not 1 <= per_page <= 50:
            raise ValueError(
                "per_page must be between 1 and 50"
            )

        params: Dict[str, Any] = {
            "page": page,
            "per_page": per_page,
        }

        if updated_since:
            params["updated_since"] = updated_since

        data = self._json_request(
            "GET",
            "/api/v2/tickets",
            params=params,
        )

        return self._extract_ticket_list(data)

    @staticmethod
    def _extract_ticket_list(
        data: Any,
    ) -> List[Dict[str, Any]]:
        """
        Normalize the ticket-list response.

        The assignment's API returns ticket records. This helper
        also tolerates a common wrapper shape if encountered.
        """
        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            for key in (
                "tickets",
                "data",
                "results",
            ):
                value = data.get(key)

                if isinstance(value, list):
                    return value

        raise FieldServeAPIError(
            "Unexpected response format from /api/v2/tickets"
        )

    def list_all_tickets(
        self,
        per_page: int = 50,
        updated_since: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch all tickets available through the paginated API.

        The assignment caps page numbers at 10. Therefore this method
        deliberately stops at page 10. Incremental synchronization
        can use updated_since to retrieve changes beyond that window.
        """
        if not 1 <= per_page <= 50:
            raise ValueError(
                "per_page must be between 1 and 50"
            )

        tickets: List[Dict[str, Any]] = []

        for page in range(1, 11):
            page_tickets = self.list_tickets_page(
                page=page,
                per_page=per_page,
                updated_since=updated_since,
            )

            if not page_tickets:
                break

            tickets.extend(page_tickets)

            if len(page_tickets) < per_page:
                break

        return tickets