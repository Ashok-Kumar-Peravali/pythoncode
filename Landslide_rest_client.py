#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Landslide REST – OO client & Postman runner

Features
- Loads a Postman v2.1 collection (JSON)
- Represents each request as an object (RequestItem)
- Executes requests with retries, timeouts, and per-request Basic Auth
- Extensible convenience client (LandslideClient) where you can add typed methods

Usage
  python landslide_client.py --collection Landslide_REST.postman_collection.json --list
  python landslide_client.py --collection Landslide_REST.postman_collection.json --run "LS Login request"

Environment variables (recommended)
  API_BASE_URL     e.g. http://10.59.224.101:8080
  API_USERNAME     e.g. sms
  API_PASSWORD     e.g. ********
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlunparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# -------------------------------
# Exceptions
# -------------------------------

class ApiError(Exception):
    """Generic API error with helpful context."""
    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[Any] = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details

# -------------------------------
# Models
# -------------------------------

@dataclass
class AuthSpec:
    type: Optional[str] = None  # e.g., "basic"
    username: Optional[str] = None
    password: Optional[str] = None

@dataclass
class RequestBody:
    mode: Optional[str] = None          # e.g., "raw", "formdata", "urlencoded"
    raw: Optional[str] = None           # raw JSON/text if mode == "raw"
    formdata: Optional[List[Dict[str, Any]]] = None
    urlencoded: Optional[List[Dict[str, Any]]] = None

@dataclass
class URLSpec:
    raw: Optional[str] = None
    protocol: Optional[str] = None
    host: Optional[List[str]] = None
    port: Optional[str] = None
    path: Optional[List[str]] = None
    query: Optional[List[Dict[str, str]]] = None

    def to_absolute(self) -> str:
        """Construct an absolute URL string from Postman URL fields (prefers 'raw' if present)."""
        if self.raw:
            return self.raw
        # Fallback: compose URL
        host_str = ""
        if self.host:
            host_str = ".".join(self.host) if self.protocol in ("ws", "wss") else ".".join(self.host).replace("..", ".")
            # Some collections store host parts like ["10","59","224","101"]; join with dots
            try:
                if all(h.isdigit() for h in self.host):
                    host_str = ".".join(self.host)
            except Exception:
                pass
        netloc = host_str
        if self.port:
            netloc = f"{host_str}:{self.port}"
        path_str = "/".join(self.path or [])
        scheme = self.protocol or "http"
        return urlunparse((scheme, netloc, f"/{path_str}".replace("//", "/"), "", "", ""))

@dataclass
class RequestItem:
    name: str
    method: str
    url: URLSpec
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[RequestBody] = None
    auth: Optional[AuthSpec] = None

    @staticmethod
    def from_postman_item(item: Dict[str, Any]) -> Optional["RequestItem"]:
        """Create RequestItem from a Postman 'item' (only if it is a request, not a folder)."""
        if "request" not in item:
            return None
        req = item["request"]

        # URL
        url_dict = req.get("url", {})
        url = URLSpec(
            raw=url_dict.get("raw"),
            protocol=url_dict.get("protocol"),
            host=url_dict.get("host"),
            port=url_dict.get("port"),
            path=url_dict.get("path"),
            query=url_dict.get("query"),
        )

        # Headers
        headers: Dict[str, str] = {}
        for h in req.get("header", []):
            key = h.get("key")
            val = h.get("value")
            if key and val is not None:
                headers[key] = str(val)

        # Body
        body_spec = None
        if "body" in req:
            b = req["body"]
            body_spec = RequestBody(
                mode=b.get("mode"),
                raw=b.get("raw"),
                formdata=b.get("formdata"),
                urlencoded=b.get("urlencoded"),
            )

        # Auth
        auth_spec = None
        if "auth" in req:
            a = req["auth"]
            a_type = a.get("type")
            username = None
            password = None
            if a_type == "basic":
                # Postman basic auth values are often in a list of dicts under a[a_type]
                kv = {entry.get("key"): entry.get("value") for entry in a.get("basic", []) if isinstance(entry, dict)}
                username = kv.get("username")
                password = kv.get("password")
            auth_spec = AuthSpec(type=a_type, username=username, password=password)

        return RequestItem(
            name=item.get("name", "Unnamed"),
            method=req.get("method", "GET").upper(),
            url=url,
            headers=headers,
            body=body_spec,
            auth=auth_spec,
        )

# -------------------------------
# HTTP Client
# -------------------------------

class ApiClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        default_timeout: int = 30,
        max_retries: int = 3,
        backoff_factor: float = 0.3,
        verify_ssl: bool = True,
        default_auth: Optional[Tuple[str, str]] = None,
        default_headers: Optional[Dict[str, str]] = None,
    ):
        self.base_url = base_url.rstrip("/") if base_url else None
        self.default_timeout = default_timeout
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.session.headers.update(default_headers or {})

        if default_auth:
            self.session.auth = default_auth

        # Set up robust retries for idempotent methods + POST (if desired)
        retry = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=False,  # retry on all methods including POST
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _prepare_url(self, item_url: URLSpec) -> str:
        absolute = item_url.to_absolute()
        if self.base_url and absolute.startswith("/"):
            return urljoin(self.base_url + "/", absolute.lstrip("/"))
        if self.base_url and absolute.startswith(("http://", "https://")) is False:
            # Treat absolute as path relative to base_url
            return urljoin(self.base_url + "/", absolute.lstrip("/"))
        return absolute

    def _prepare_body(self, body: Optional[RequestBody]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Return (data_kwargs, headers_override) for requests."""
        if not body or not body.mode:
            return {}, {}
        if body.mode == "raw":
            # Assume raw JSON if it looks like JSON, else plain text
            raw = body.raw or ""
            try:
                json_payload = json.loads(raw)
                return ({"json": json_payload}, {"Content-Type": "application/json"})
            except Exception:
                return ({"data": raw}, {"Content-Type": "text/plain"})
        if body.mode == "formdata":
            # Postman "formdata" may include files; here we treat all as fields
            fields = {}
            files = {}
            for part in body.formdata or []:
                key = part.get("key")
                if not key:
                    continue
                if part.get("type") == "file":
                    # Expect 'src' path; you can expand this logic as needed
                    src = part.get("src")
                    if src:
                        files[key] = open(src, "rb")
                else:
                    fields[key] = part.get("value")
            return ({"data": fields, "files": files}, {})
        if body.mode == "urlencoded":
            fields = {p.get("key"): p.get("value") for p in body.urlencoded or [] if p.get("key")}
            return ({"data": fields}, {"Content-Type": "application/x-www-form-urlencoded"})
        return {}, {}

    def send(self, req_item: RequestItem, timeout: Optional[int] = None) -> requests.Response:
        url = self._prepare_url(req_item.url)
        headers = dict(self.session.headers)
        headers.update(req_item.headers or {})
        data_kwargs, body_headers = self._prepare_body(req_item.body)
        headers.update(body_headers)

        # Per-request auth overrides session auth if present
        auth = self.session.auth
        if req_item.auth and req_item.auth.type == "basic":
            user = req_item.auth.username
            pwd = req_item.auth.password
            auth = (user, pwd)

        try:
            resp = self.session.request(
                method=req_item.method.upper(),
                url=url,
                headers=headers,
                timeout=timeout or self.default_timeout,
                auth=auth,
                **data_kwargs,
            )
            return resp
        except requests.RequestException as e:
            raise ApiError(f"Request failed: {e}") from e

# -------------------------------
# Postman Collection Loader & Runner
# -------------------------------

class PostmanCollection:
    def __init__(self, items: List[RequestItem]):
        self.items = items
        self.by_name = {it.name: it for it in items}

    @staticmethod
    def load(path: str) -> "PostmanCollection":
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)

        def flatten_items(items: List[Dict[str, Any]]) -> List[RequestItem]:
            out: List[RequestItem] = []
            for it in items:
                if "item" in it and isinstance(it["item"], list):
                    out.extend(flatten_items(it["item"]))  # folder
                else:
                    req = RequestItem.from_postman_item(it)
                    if req:
                        out.append(req)
            return out

        items = flatten_items(doc.get("item", []))
        return PostmanCollection(items)

class PostmanRunner:
    def __init__(self, client: ApiClient, collection: PostmanCollection):
        self.client = client
        self.collection = collection

    def list_requests(self) -> List[str]:
        return list(self.collection.by_name.keys())

    def run_by_name(self, name: str) -> requests.Response:
        if name not in self.collection.by_name:
            raise ApiError(f"Request named '{name}' not found in collection.")
        req_item = self.collection.by_name[name]
        return self.client.send(req_item)

# -------------------------------
# Convenience API Wrapper (customize/extend)
# -------------------------------

class LandslideClient:
    """
    A typed convenience wrapper you can extend with known endpoints.
    Uses ApiClient under the hood. Add methods as your API grows.
    """
    def __init__(self, api: ApiClient):
        self.api = api

    def login(self, username: Optional[str] = None, password: Optional[str] = None) -> requests.Response:
        """
        Performs the 'LS Login request' as seen in the collection, using Basic Auth.
        If username/password are provided here, they override defaults.
        """
        # Build a minimal RequestItem matching the Postman request:
        # POST http://<base-or-raw>/api/login with Basic Auth
        url = URLSpec(raw="/api/login")  # if your API_BASE_URL is set, this becomes absolute
        auth = None
        if username and password:
            auth = AuthSpec(type="basic", username=username, password=password)
        req = RequestItem(
            name="LS Login request",
            method="POST",
            url=url,
            headers={"Accept": "application/json"},
            body=None,
            auth=auth,
        )
        return self.api.send(req)

    # Example placeholders (adjust paths/names once confirmed in your collection)
    def test_servers(self) -> requests.Response:
        """GET /api/testServers (adjust path if different)."""
        req = RequestItem(
            name="testServers",
            method="GET",
            url=URLSpec(raw="/api/testServers"),
            headers={"Accept": "application/json"},
        )
        return self.api.send(req)

    def running_tests(self) -> requests.Response:
        """GET /api/runningTests (adjust path if different)."""
        req = RequestItem(
            name="runningTests",
            method="GET",
            url=URLSpec(raw="/api/runningTests"),
            headers={"Accept": "application/json"},
        )
        return self.api.send(req)

# -------------------------------
# CLI
# -------------------------------

def build_logger(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

def main():
    parser = argparse.ArgumentParser(description="Landslide REST – OO client & Postman runner")
    parser.add_argument("--collection", "-c", required=True, help="Path to Postman collection JSON")
    parser.add_argument("--base-url", "-b", help="Base URL (falls back to $API_BASE_URL if not provided)")
    parser.add_argument("--verify-ssl", action="store_true", default=False, help="Verify SSL certs (default: False)")
    parser.add_argument("--list", action="store_true", help="List request names in the collection and exit")
    parser.add_argument("--run", help="Run a request by its name in the collection")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout seconds (default: 30)")
    parser.add_argument("--retries", type=int, default=3, help="Max retries (default: 3)")
    parser.add_argument("--verbose", "-v", action="count", default=0, help="Increase verbosity (-v, -vv)")

    args = parser.parse_args()
    build_logger(args.verbose)

    base_url = args.base_url or os.getenv("API_BASE_URL")
    user = os.getenv("API_USERNAME")
    pwd = os.getenv("API_PASSWORD")

    default_auth = (user, pwd) if user and pwd else None

    # Load collection
    try:
        collection = PostmanCollection.load(args.collection)
    except Exception as e:
        logging.error("Failed to load collection: %s", e)
        sys.exit(1)

    # Init low-level client
    api = ApiClient(
        base_url=base_url,
        default_timeout=args.timeout,
        max_retries=args.retries,
        verify_ssl=args.verify_ssl,
        default_auth=default_auth,
        default_headers={"Accept": "application/json"},
    )

    # Option A: List or run arbitrary collection requests
    runner = PostmanRunner(api, collection)
    if args.list:
        for name in runner.list_requests():
            print(name)
        return

    if args.run:
        resp = runner.run_by_name(args.run)
        print(f"HTTP {resp.status_code}")
        ct = resp.headers.get("Content-Type", "")
        if "application/json" in ct:
            try:
                print(json.dumps(resp.json(), indent=2))
            except Exception:
                print(resp.text)
        else:
            print(resp.text)
        return

    # Option B: Use the typed convenience wrapper
    landslide = LandslideClient(api)
    if user and pwd:
        resp = landslide.login()  # uses default_auth from session
        print(f"Login -> HTTP {resp.status_code}")
        print(resp.text)
    else:
        print("No action taken. Provide --run or set API_USERNAME/API_PASSWORD to try LandslideClient.login().")

if __name__ == "__main__":
    main()