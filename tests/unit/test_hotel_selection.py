"""酒店优选单元测试：地理均值 + LLM 选酒店 + 搜索参数。"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from travel_assistant.domain.models import Hotel, POI


# ---------- 地理均值计算 ----------

class TestGeometricMean:
    def test_three_pois_mean(self):
        pois = [
            POI(name="A", lng=104.0, lat=30.0),
            POI(name="B", lng=105.0, lat=31.0),
            POI(name="C", lng=106.0, lat=32.0),
        ]
        top3 = pois[:3]
        center_lng = sum(p.lng for p in top3) / len(top3)
        center_lat = sum(p.lat for p in top3) / len(top3)
        assert center_lng == pytest.approx(105.0)
        assert center_lat == pytest.approx(31.0)

    def test_two_pois_mean(self):
        pois = [
            POI(name="A", lng=104.0, lat=30.0),
            POI(name="B", lng=106.0, lat=32.0),
        ]
        top3 = pois[:2]
        center_lng = sum(p.lng for p in top3) / len(top3)
        center_lat = sum(p.lat for p in top3) / len(top3)
        assert center_lng == pytest.approx(105.0)
        assert center_lat == pytest.approx(31.0)

    def test_one_poi_mean(self):
        pois = [POI(name="A", lng=104.0, lat=30.0)]
        top3 = pois[:1]
        center_lng = sum(p.lng for p in top3) / len(top3)
        center_lat = sum(p.lat for p in top3) / len(top3)
        assert center_lng == pytest.approx(104.0)
        assert center_lat == pytest.approx(30.0)


# ---------- around_tool 搜索参数 ----------

class TestAroundToolParams:
    def test_hotel_type_is_100000(self):
        # 高德分类 100000=住宿服务；010000 是汽车服务（租车/充电站），曾导致搜出租车行
        from travel_assistant.tools.around_tool import HOTEL_TYPE
        assert HOTEL_TYPE == "100000"

    def test_hotel_default_radius_3000(self):
        import inspect
        from travel_assistant.tools.around_tool import search_hotels
        sig = inspect.signature(search_hotels)
        assert sig.parameters["radius"].default == 3000

    def test_restaurant_default_radius_3000(self):
        import inspect
        from travel_assistant.tools.around_tool import search_restaurants
        sig = inspect.signature(search_restaurants)
        assert sig.parameters["radius"].default == 3000


# ---------- select_hotel_by_llm ----------

def _hotel(name, distance=500, lng=104.0, lat=30.0):
    return Hotel(name=name, lng=lng, lat=lat, distance=distance, kind="hotel")


class TestSelectHotelByLlm:
    @pytest.mark.asyncio
    async def test_empty_hotels_returns_none(self):
        from travel_assistant.llm.hotel_selection import select_hotel_by_llm
        result = await select_hotel_by_llm([], ["穷游"])
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_selects_hotel(self):
        from travel_assistant.llm.hotel_selection import select_hotel_by_llm
        hotels = [_hotel(f"酒店{i}") for i in range(5)]
        mock_llm = AsyncMock(return_value={
            "selected_hotel": "酒店2",
            "reason": "经济实惠",
        })
        with patch("travel_assistant.llm.hotel_selection.get_llm_client") as mock_client:
            mock_client.return_value.chat_json = mock_llm
            result = await select_hotel_by_llm(hotels, ["穷游"])
        assert result is not None
        assert result.name == "酒店2"

    @pytest.mark.asyncio
    async def test_llm_returns_invalid_hotel_name(self):
        from travel_assistant.llm.hotel_selection import select_hotel_by_llm
        hotels = [_hotel(f"酒店{i}") for i in range(5)]
        mock_llm = AsyncMock(return_value={
            "selected_hotel": "不存在的酒店",
            "reason": "test",
        })
        with patch("travel_assistant.llm.hotel_selection.get_llm_client") as mock_client:
            mock_client.return_value.chat_json = mock_llm
            result = await select_hotel_by_llm(hotels, ["穷游"])
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_failure_returns_none(self):
        from travel_assistant.llm.hotel_selection import select_hotel_by_llm
        hotels = [_hotel(f"酒店{i}") for i in range(5)]
        with patch("travel_assistant.llm.hotel_selection.get_llm_client") as mock_client:
            mock_client.return_value.chat_json = AsyncMock(return_value=None)
            result = await select_hotel_by_llm(hotels, ["穷游"])
        assert result is None

    @pytest.mark.asyncio
    async def test_no_preferences_still_works(self):
        from travel_assistant.llm.hotel_selection import select_hotel_by_llm
        hotels = [_hotel(f"酒店{i}") for i in range(5)]
        mock_llm = AsyncMock(return_value={
            "selected_hotel": "酒店0",
            "reason": "距离最近",
        })
        with patch("travel_assistant.llm.hotel_selection.get_llm_client") as mock_client:
            mock_client.return_value.chat_json = mock_llm
            result = await select_hotel_by_llm(hotels, [])
        assert result is not None
        assert result.name == "酒店0"


# ---------- hotel_agent 节点 ----------

class TestHotelAgentNode:
    @pytest.mark.asyncio
    async def test_no_pois_returns_empty(self):
        from travel_assistant.agents.hotel_agent import hotel_agent
        result = await hotel_agent({"pois": [], "preferences": []})
        assert result["hotels"] == []
        assert result["restaurants"] == []
        assert "warnings" in result

    @pytest.mark.asyncio
    async def test_top3_geometric_mean_used(self):
        from travel_assistant.agents.hotel_agent import hotel_agent
        pois = [
            POI(name=f"景点{i}", lng=104.0 + i, lat=30.0 + i)
            for i in range(5)
        ]
        # Expected center: (104+105+106)/3 = 105.0, (30+31+32)/3 = 31.0
        with patch("travel_assistant.agents.hotel_agent.search_hotels", new_callable=AsyncMock) as mock_hotels, \
             patch("travel_assistant.agents.hotel_agent.search_restaurants", new_callable=AsyncMock) as mock_rest:
            mock_hotels.return_value = []
            mock_rest.return_value = []
            result = await hotel_agent({"pois": pois, "preferences": []})
            # Verify search_hotels called with geometric mean coordinates (positional args)
            call_args = mock_hotels.call_args
            assert call_args.args[0] == pytest.approx(105.0)  # lng
            assert call_args.args[1] == pytest.approx(31.0)   # lat
            assert call_args.kwargs["radius"] == 3000

    @pytest.mark.asyncio
    async def test_llm_selection_reorders_hotels(self):
        from travel_assistant.agents.hotel_agent import hotel_agent
        pois = [POI(name=f"景点{i}", lng=104.0 + i, lat=30.0 + i) for i in range(3)]
        hotels = [_hotel(f"酒店{i}") for i in range(5)]
        selected = _hotel("酒店3")

        with patch("travel_assistant.agents.hotel_agent.search_hotels", new_callable=AsyncMock) as mock_hotels, \
             patch("travel_assistant.agents.hotel_agent.search_restaurants", new_callable=AsyncMock) as mock_rest, \
             patch("travel_assistant.agents.hotel_agent.select_hotel_by_llm", new_callable=AsyncMock) as mock_sel:
            mock_hotels.return_value = hotels
            mock_rest.return_value = []
            mock_sel.return_value = selected
            result = await hotel_agent({"pois": pois, "preferences": ["穷游"]})

        # Selected hotel should be first
        assert result["hotels"][0].name == "酒店3"
        # Total still 5 (reordered, not filtered)
        assert len(result["hotels"]) == 5

    @pytest.mark.asyncio
    async def test_llm_failure_keeps_original_order(self):
        from travel_assistant.agents.hotel_agent import hotel_agent
        pois = [POI(name=f"景点{i}", lng=104.0 + i, lat=30.0 + i) for i in range(3)]
        hotels = [_hotel(f"酒店{i}") for i in range(5)]

        with patch("travel_assistant.agents.hotel_agent.search_hotels", new_callable=AsyncMock) as mock_hotels, \
             patch("travel_assistant.agents.hotel_agent.search_restaurants", new_callable=AsyncMock) as mock_rest, \
             patch("travel_assistant.agents.hotel_agent.select_hotel_by_llm", new_callable=AsyncMock) as mock_sel:
            mock_hotels.return_value = hotels
            mock_rest.return_value = []
            mock_sel.return_value = None
            result = await hotel_agent({"pois": pois, "preferences": ["穷游"]})

        assert result["hotels"][0].name == "酒店0"  # original order preserved
        assert len(result["hotels"]) == 5
