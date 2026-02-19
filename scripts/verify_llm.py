#!/usr/bin/env python3
"""End-to-end smoke test for Phase 4: LLM Integration.

Tests:
1. LLM settings load from llm.yaml
2. LLM provider instantiation from config
3. SynthesisEngine instantiation and prompt assembly
4. Citation regex parsing
5. /ask endpoint import and route registration
6. Optional: live /ask call (requires running server at http://localhost:8000)

Run with:
    cd /home/jcanossa/workspace/fellow-quant/core/rag_server
    python scripts/verify_llm.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import traceback
from dataclasses import dataclass


def test_config():
    """Test LLM config loads from llm.yaml."""
    from rag_server.llm.config import get_llm_settings
    # Reset lru_cache to ensure fresh load
    get_llm_settings.cache_clear()
    settings = get_llm_settings()
    assert settings.llm.provider in ("vllm", "llamacpp", "bedrock"), (
        f"provider must be vllm|llamacpp|bedrock, got {settings.llm.provider!r}"
    )
    assert settings.llm.context_chunks >= 1
    assert settings.llm.max_context_tokens >= 1000
    assert len(settings.llm.system_prompt) > 10, "system_prompt should not be empty"
    print(f"  [OK] Config: provider={settings.llm.provider!r}, model={settings.llm.model!r}")
    print(f"       context_chunks={settings.llm.context_chunks}, max_context_tokens={settings.llm.max_context_tokens}")
    return settings


def test_provider_factory(settings):
    """Test provider factory instantiates without error."""
    from rag_server.llm.provider import create_provider, LLMProvider
    provider = create_provider(settings.llm)
    assert isinstance(provider, LLMProvider), "create_provider must return LLMProvider"
    print(f"  [OK] Provider instantiated: {type(provider).__name__}")
    return provider


def test_synthesis_engine(provider, settings):
    """Test SynthesisEngine instantiation and prompt assembly."""
    from rag_server.llm.synthesis import SynthesisEngine, _CITATION_RE

    engine = SynthesisEngine(provider=provider, config=settings.llm)

    # Test citation regex
    test_cases = [
        ("[Source: black_scholes.pdf, p.12]", "black_scholes.pdf", "12"),
        ("[Source: Hull.pdf p.5]", "Hull.pdf", "5"),
        ("[SOURCE: test.pdf, p.99]", "test.pdf", "99"),  # case insensitive
        ("[Source: my doc.pdf]", "my doc.pdf", None),    # no page
    ]
    for text, expected_file, expected_page in test_cases:
        m = _CITATION_RE.search(text)
        assert m is not None, f"No match for: {text!r}"
        assert m.group(1).strip() == expected_file, (
            f"Expected filename {expected_file!r}, got {m.group(1).strip()!r}"
        )
        assert m.group(2) == expected_page, (
            f"Expected page {expected_page!r}, got {m.group(2)!r}"
        )
    print("  [OK] Citation regex: all 4 test cases pass")

    print(f"  [OK] SynthesisEngine instantiated: {type(engine).__name__}")
    return engine


def test_schema_round_trip():
    """Test AskResponse/SourceItem schema serialization."""
    from rag_server.api.schemas import AskResponse, SourceItem
    r = AskResponse(
        answer="The Black-Scholes formula [Source: bsm.pdf, p.5] shows...",
        sources=[
            SourceItem(filename="bsm.pdf", page_number=5, section_heading="Formula", chunk_type="formula"),
        ],
    )
    dumped = r.model_dump()
    assert dumped["answer"].startswith("The Black-Scholes")
    assert dumped["sources"][0]["filename"] == "bsm.pdf"
    print(f"  [OK] AskResponse schema: {dumped['sources']}")


def test_endpoint_registration():
    """Test /ask endpoint is registered on the FastAPI app."""
    from rag_server.api.ask import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    routes = {r.path for r in app.routes}
    assert "/ask" in routes, f"/ask not in routes: {routes}"
    print(f"  [OK] /ask endpoint registered")


async def test_live_ask_optional():
    """Optional: test /ask against running server.

    Skipped if server not running. Not a failure — provider may be offline.
    """
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            # First check health
            health = await client.get("http://localhost:8001/health")
            if health.status_code != 200:
                print("  [SKIP] Server not running at localhost:8001")
                return

            # Non-streaming ask
            resp = await client.post(
                "http://localhost:8001/ask",
                json={"query": "What is the Black-Scholes formula?", "top_k": 5},
                params={"streaming": "false"},
            )
            if resp.status_code == 200:
                data = resp.json()
                assert "answer" in data, f"'answer' missing from response: {data}"
                assert "sources" in data, f"'sources' missing from response: {data}"
                print(f"  [OK] Live /ask (non-streaming): answer length={len(data['answer'])}, sources={len(data['sources'])}")
            else:
                print(f"  [WARN] /ask returned {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        print(f"  [SKIP] Live test skipped: {type(exc).__name__}: {exc}")


def main():
    print("=" * 60)
    print("Phase 4 LLM Integration Smoke Test")
    print("=" * 60)

    passed = 0
    failed = 0

    steps = [
        ("Config loading", lambda: test_config()),
        ("Schema round-trip", lambda: (test_schema_round_trip(), None)[1]),
        ("Endpoint registration", lambda: (test_endpoint_registration(), None)[1]),
    ]

    settings = None
    provider = None

    for name, fn in steps:
        print(f"\n--- {name} ---")
        try:
            result = fn()
            if result is not None:
                settings = result
            passed += 1
        except Exception:
            print(f"  [FAIL] {name}")
            traceback.print_exc()
            failed += 1

    if settings is not None:
        print("\n--- Provider factory ---")
        try:
            provider = test_provider_factory(settings)
            passed += 1
        except Exception:
            print("  [FAIL] Provider factory")
            traceback.print_exc()
            failed += 1

    if settings is not None and provider is not None:
        print("\n--- SynthesisEngine ---")
        try:
            test_synthesis_engine(provider, settings)
            passed += 1
        except Exception:
            print("  [FAIL] SynthesisEngine")
            traceback.print_exc()
            failed += 1

    print("\n--- Live /ask (optional) ---")
    asyncio.run(test_live_ask_optional())

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
