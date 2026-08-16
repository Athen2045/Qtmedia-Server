import os
import sys

try:
    import chardet
except ModuleNotFoundError:  # pragma: no cover - exercised in Theia's main test env
    chardet = None

import requests

sys.path.append(os.path.join(os.path.dirname(__file__), "."))

from log import logError

requests.packages.urllib3.disable_warnings()


def _decode_binary_content(binary_content):
    if chardet is not None:
        encode = chardet.detect(binary_content).get("encoding")
        if encode:
            return binary_content.decode(encode)
    return binary_content.decode("utf-8", errors="replace")


# Perform a Sync Request and return response details
def do_sync_request(method, url, config, data=None, customHeaders=None, cookies=None):
    headers = {"User-Agent": config.userAgent}
    if customHeaders:
        headers.update(customHeaders)
    # Only set proxies parameter if actually needed to avoid performance overhead
    request_kwargs = {
        "method": method,
        "url": url,
        "timeout": config.timeout,
        "verify": True,
        "headers": headers,
        "data": data,
        "cookies": cookies,
    }
    
    # Only add proxies parameter if a proxy is actually configured
    if config.proxy:
        request_kwargs["proxies"] = {"http": config.proxy, "https": config.proxy}
    try:
        response = requests.request(**request_kwargs)
        if config.verbose:
            config.console.print(
                f"  🆗 Sync HTTP Request completed [{method} - {response.status_code}] {url}"
            )
        return response
    except requests.RequestException as e:
        if config.verbose:
            config.console.print(f"  ❌ Error in Sync HTTP Request [{method}] {url}")
        logError(e, f"Error in Sync HTTP Request [{method}] {url}", config)
        return None


# Perform an Async Request and return response details
async def do_async_request(method, url, session, config, data=None, customHeaders=None):
    headers = {"User-Agent": config.userAgent}
    if customHeaders:
        headers.update(customHeaders)
    proxy = config.proxy if config.proxy else None
    try:
        response = await session.request(
            method,
            url,
            proxy=proxy,
            timeout=config.timeout,
            allow_redirects=True,
            ssl=True,
            data=data,
            headers=headers,
            max_redirects=10,
        )

        json = None
        try:
            content = await response.text()
        except (LookupError, TypeError, UnicodeDecodeError, ValueError):
            binaryContent = await response.read()
            content = _decode_binary_content(binaryContent)

        if (
            "Content-Type" in response.headers
            and "application/json" in response.headers["Content-Type"]
        ):
            json = await response.json()

        responseData = {
            "url": url,
            "status_code": response.status,
            "headers": response.headers,
            "content": content,
            "json": json,
        }

        if config.verbose:
            config.console.print(
                f"  🆗 Async HTTP Request completed [{method} - {response.status}] {url}"
            )
        return responseData
    except Exception as e:  # noqa: BLE001 - Blackbird treats any request-layer failure as a soft miss.
        if config.verbose:
            config.console.print(f"  ❌ Error in Async HTTP Request [{method}] {url}")
        logError(e, f"Error in Async HTTP Request [{method}] {url}", config)
        return None
