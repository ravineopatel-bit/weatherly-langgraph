import os
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
import web_app


class WebTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"APP_PASSWORD": "", "RENDER": "", "OPENAI_API_KEY": "test-only"})
        self.env.start()
        web_app.sessions.clear()
        self.client = TestClient(web_app.app)

    def tearDown(self):
        self.client.close()
        self.env.stop()

    def test_page_and_secrets_are_not_served(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/.env").status_code, 404)
        self.assertEqual(self.client.get("/static/../.env").status_code, 404)

    def test_password_gate_and_health(self):
        with patch.dict(os.environ, {"APP_PASSWORD": "test-password"}):
            self.assertEqual(self.client.get("/").status_code, 401)
            self.assertEqual(self.client.get("/healthz").status_code, 200)
            self.assertEqual(self.client.get("/", auth=("weather", "test-password")).status_code, 200)

    def test_hosted_app_requires_password(self):
        with patch.dict(os.environ, {"RENDER": "true", "APP_PASSWORD": ""}):
            self.assertEqual(self.client.get("/").status_code, 503)

    def test_chat_history_is_separate_and_reset_works(self):
        fake = Mock()
        fake.invoke.side_effect = lambda state, config: {"messages": [*state["messages"], AIMessage(content="Sunny") ]}
        with patch.object(web_app, "agent", fake):
            self.client.get("/api/session")
            reply = self.client.post("/api/chat", json={"message": "Mumbai weather?"})
            self.assertEqual(reply.json()["answer"], "Sunny")
            self.assertEqual(self.client.get("/api/session").json()["turns"], 1)
            with TestClient(web_app.app) as other:
                self.assertEqual(other.get("/api/session").json()["turns"], 0)
            self.client.post("/api/reset")
            self.assertEqual(self.client.get("/api/session").json()["turns"], 0)

    def test_validation_and_cross_origin_protection(self):
        self.assertEqual(self.client.post("/api/chat", json={"message": " "}).status_code, 422)
        self.assertEqual(self.client.post("/api/chat", json={"message": "x" * 2001}).status_code, 422)
        self.assertEqual(self.client.post("/api/chat", json={"message": "Hi"}, headers={"origin": "https://other.example"}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
