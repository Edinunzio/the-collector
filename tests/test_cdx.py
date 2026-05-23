"""Tests for the Internet Archive CDX API client."""
import pytest
import respx
import httpx
from collector.crawler.cdx import fetch_cdx_urls, CDX_API_URL


@respx.mock
async def test_fetch_cdx_urls_returns_live_urls():
    """CDX client should parse the API response and return (url, timestamp) tuples."""
    mock_response = (
        '["urlkey","timestamp","original","statuscode"]\n'
        '["com,example)/fish.html","19990315120000","http://example.com/fish.html","200"]\n'
        '["com,example)/tanks.html","20010822093012","http://example.com/tanks.html","200"]\n'
        '["com,example)/old.html","20030110080000","http://example.com/old.html","404"]\n'
    )
    respx.get(CDX_API_URL).mock(return_value=httpx.Response(200, text=mock_response))

    results = await fetch_cdx_urls(from_year=1996, to_year=2005, limit=10)
    # Should only include status 200 URLs
    assert len(results) == 2
    urls = [r[0] for r in results]
    assert "http://example.com/fish.html" in urls
    assert "http://example.com/tanks.html" in urls
    # 404 should be excluded
    assert "http://example.com/old.html" not in urls


@respx.mock
async def test_fetch_cdx_urls_handles_empty_response():
    mock_response = '["urlkey","timestamp","original","statuscode"]\n'
    respx.get(CDX_API_URL).mock(return_value=httpx.Response(200, text=mock_response))

    results = await fetch_cdx_urls(from_year=1996, to_year=2000, limit=10)
    assert results == []


@respx.mock
async def test_fetch_cdx_urls_handles_api_error():
    respx.get(CDX_API_URL).mock(return_value=httpx.Response(500))

    results = await fetch_cdx_urls(from_year=1996, to_year=2000, limit=10)
    assert results == []
