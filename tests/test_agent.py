import unittest
from unittest.mock import patch

import httpx
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from weather_agent import build_agent, get_weather, request_json, search_locations


class ScriptedModel:
    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content="Weather retrieved.")
        return AIMessage(content="", tool_calls=[{
            "name": "get_weather", "args": {"latitude": 19.07, "longitude": 72.87},
            "id": "weather-1", "type": "tool_call",
        }])


class WeatherTests(unittest.TestCase):
    @patch("weather_agent.request_json", return_value={"current": {"temperature_2m": 25}})
    def test_graph_executes_tool_and_returns_to_model(self, request):
        result = build_agent(ScriptedModel()).invoke({"messages": [HumanMessage(content="Weather?")]})
        self.assertEqual(result["messages"][-1].content, "Weather retrieved.")
        self.assertTrue(any(isinstance(m, ToolMessage) for m in result["messages"]))
        request.assert_called_once()

    @patch("weather_agent.request_json", return_value={})
    def test_fahrenheit_and_forecast_parameters(self, request):
        get_weather.invoke({"latitude": 1, "longitude": 2, "days": 2, "units": "fahrenheit"})
        params = request.call_args.args[1]
        self.assertEqual(params["temperature_unit"], "fahrenheit")
        self.assertEqual(params["wind_speed_unit"], "mph")
        self.assertEqual(params["forecast_days"], 2)
        self.assertEqual(params["timezone"], "auto")

    @patch("weather_agent.request_json")
    def test_invalid_coordinates_and_horizon_do_not_fetch(self, request):
        for args in ({"latitude": 91, "longitude": 0},
                     {"latitude": 0, "longitude": 0, "days": 8}):
            self.assertIn("error", get_weather.invoke(args))
        request.assert_not_called()

    @patch("weather_agent.request_json", return_value={})
    def test_unknown_city(self, request):
        self.assertEqual(search_locations.invoke({"city": "Unknown"}), {"locations": []})

    @patch("weather_agent.httpx.get", side_effect=httpx.ConnectError("offline"))
    def test_network_failure(self, request):
        self.assertIn("error", request_json("https://api.open-meteo.com/v1/forecast", {}))


if __name__ == "__main__":
    unittest.main()
