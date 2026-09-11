"""POI 天气过滤单元测试：is_bad_weather + LLM 分类 + 兜底。"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from travel_assistant.domain.models import POI, Weather
from travel_assistant.tools.weather_tool import is_bad_weather, BAD_WEATHER_KEYWORDS
from travel_assistant.llm.poi_filter import filter_outdoor_pois, MIN_POI_AFTER_FILTER


# ---------- is_bad_weather ----------

class TestIsBadWeather:
    def test_sunny_is_good(self):
        assert not is_bad_weather("晴")

    def test_cloudy_is_good(self):
        assert not is_bad_weather("多云")

    def test_rain_is_bad(self):
        assert is_bad_weather("小雨")

    def test_heavy_rain_is_bad(self):
        assert is_bad_weather("暴雨")

    def test_snow_is_bad(self):
        assert is_bad_weather("小雪")

    def test_thunder_is_bad(self):
        assert is_bad_weather("雷阵雨")

    def test_fog_is_bad(self):
        assert is_bad_weather("雾")

    def test_haze_is_bad(self):
        assert is_bad_weather("霾")

    def test_unknown_is_good(self):
        assert not is_bad_weather("unavailable")

    def test_empty_string_is_good(self):
        assert not is_bad_weather("")

    def test_all_keywords_covered(self):
        for kw in BAD_WEATHER_KEYWORDS:
            assert is_bad_weather(kw)


# ---------- filter_outdoor_pois ----------

def _poi(name, lng=104.0, lat=30.0):
    return POI(name=name, lng=lng, lat=lat)


class TestFilterOutdoorPois:
    @pytest.mark.asyncio
    async def test_empty_pois_returns_empty(self):
        result = await filter_outdoor_pois([])
        assert result == []

    @pytest.mark.asyncio
    async def test_llm_classifies_and_filters_outdoor(self):
        pois = [
            _poi("成都博物馆"),
            _poi("人民公园"),
            _poi("天府广场"),
            _poi("四川博物院"),
            _poi("浣花溪公园"),
            _poi("科技馆"),
            _poi("美术馆"),
            _poi("图书馆"),
        ]
        mock_llm = AsyncMock(return_value={
            "classifications": [
                {"name": "成都博物馆", "indoor": True},
                {"name": "人民公园", "indoor": False},
                {"name": "天府广场", "indoor": False},
                {"name": "四川博物院", "indoor": True},
                {"name": "浣花溪公园", "indoor": False},
                {"name": "科技馆", "indoor": True},
                {"name": "美术馆", "indoor": True},
                {"name": "图书馆", "indoor": True},
            ]
        })
        with patch("travel_assistant.llm.poi_filter.get_llm_client") as mock_client:
            mock_client.return_value.chat_json = mock_llm
            result = await filter_outdoor_pois(pois)

        names = [p.name for p in result]
        assert "成都博物馆" in names
        assert "四川博物院" in names
        assert "人民公园" not in names
        assert "天府广场" not in names
        assert "浣花溪公园" not in names

    @pytest.mark.asyncio
    async def test_llm_failure_keeps_all_pois(self):
        pois = [_poi(f"景点{i}") for i in range(6)]
        with patch("travel_assistant.llm.poi_filter.get_llm_client") as mock_client:
            mock_client.return_value.chat_json = AsyncMock(return_value=None)
            result = await filter_outdoor_pois(pois)
        assert len(result) == len(pois)

    @pytest.mark.asyncio
    async def test_filtered_too_few_keeps_all(self):
        pois = [_poi(f"景点{i}") for i in range(6)]
        mock_llm = AsyncMock(return_value={
            "classifications": [
                {"name": "景点0", "indoor": True},
                {"name": "景点1", "indoor": False},
                {"name": "景点2", "indoor": False},
                {"name": "景点3", "indoor": False},
                {"name": "景点4", "indoor": False},
                {"name": "景点5", "indoor": False},
            ]
        })
        with patch("travel_assistant.llm.poi_filter.get_llm_client") as mock_client:
            mock_client.return_value.chat_json = mock_llm
            result = await filter_outdoor_pois(pois)
        # Only 1 indoor POI < MIN_POI_AFTER_FILTER, should keep all
        assert len(result) == len(pois)

    @pytest.mark.asyncio
    async def test_unclassified_pois_kept(self):
        pois = [
            _poi("成都博物馆"),
            _poi("人民公园"),
            _poi("未知景点"),
            _poi("科技馆"),
            _poi("图书馆"),
        ]
        mock_llm = AsyncMock(return_value={
            "classifications": [
                {"name": "成都博物馆", "indoor": True},
                {"name": "人民公园", "indoor": False},
                # "未知景点" not classified
                {"name": "科技馆", "indoor": True},
                {"name": "图书馆", "indoor": True},
            ]
        })
        with patch("travel_assistant.llm.poi_filter.get_llm_client") as mock_client:
            mock_client.return_value.chat_json = mock_llm
            result = await filter_outdoor_pois(pois)
        names = [p.name for p in result]
        assert "成都博物馆" in names
        assert "科技馆" in names
        assert "图书馆" in names
        assert "未知景点" in names  # unclassified -> kept
        assert "人民公园" not in names  # classified as outdoor -> removed

    @pytest.mark.asyncio
    async def test_llm_returns_invalid_json_keeps_all(self):
        pois = [_poi(f"景点{i}") for i in range(6)]
        with patch("travel_assistant.llm.poi_filter.get_llm_client") as mock_client:
            mock_client.return_value.chat_json = AsyncMock(return_value={})
            result = await filter_outdoor_pois(pois)
        assert len(result) == len(pois)


# ---------- poi_filter barrier node ----------

class TestPoiFilterNode:
    @pytest.mark.asyncio
    async def test_skip_when_already_filtered(self):
        from travel_assistant.agents.poi_filter import poi_filter
        result = await poi_filter({"poi_filtered": True})
        assert result == {}

    @pytest.mark.asyncio
    async def test_skip_when_data_not_ready(self):
        from travel_assistant.agents.poi_filter import poi_filter
        result = await poi_filter({"pois": []})
        assert result == {}

    @pytest.mark.asyncio
    async def test_skip_when_good_weather(self):
        from travel_assistant.agents.poi_filter import poi_filter
        pois = [_poi("博物馆")]
        weathers = [Weather(date="2026-09-11", condition="晴", temperature="20~28℃")]
        result = await poi_filter({"pois": pois, "weathers": weathers})
        assert result == {"poi_filtered": True}

    @pytest.mark.asyncio
    async def test_skip_when_no_pois(self):
        from travel_assistant.agents.poi_filter import poi_filter
        weathers = [Weather(date="2026-09-11", condition="暴雨", temperature="15~20℃")]
        result = await poi_filter({"pois": [], "weathers": weathers})
        assert result == {"poi_filtered": True}

    @pytest.mark.asyncio
    async def test_filter_on_bad_weather(self):
        from travel_assistant.agents.poi_filter import poi_filter
        pois = [_poi(f"景点{i}") for i in range(10)]
        weathers = [Weather(date="2026-09-11", condition="大雨", temperature="15~20℃")]
        mock_llm = AsyncMock(return_value={
            "classifications": [
                {"name": f"景点{i}", "indoor": i % 2 == 0}
                for i in range(10)
            ]
        })
        with patch("travel_assistant.llm.poi_filter.get_llm_client") as mock_client:
            mock_client.return_value.chat_json = mock_llm
            result = await poi_filter({"pois": pois, "weathers": weathers})
        assert result["poi_filtered"] is True
        assert len(result["pois"]) == 5  # only indoor (even indices: 0,2,4,6,8)
