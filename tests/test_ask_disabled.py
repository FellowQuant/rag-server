import unittest
from types import SimpleNamespace

from fastapi import HTTPException, status

from rag_server.api.ask import ask
from rag_server.api.schemas import AskRequest


class AskDisabledTest(unittest.IsolatedAsyncioTestCase):
    async def test_ask_returns_503_when_synthesis_engine_missing(self) -> None:
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    retrieval_engine=object(),
                    synthesis_engine=None,
                )
            )
        )

        with self.assertRaises(HTTPException) as raised:
            await ask(
                AskRequest(query="test", top_k=1),
                request,  # type: ignore[arg-type]
                streaming=False,
            )

        self.assertEqual(
            raised.exception.status_code,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        self.assertIn("Ask synthesis is disabled", raised.exception.detail)
