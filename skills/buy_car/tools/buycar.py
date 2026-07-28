# -*- coding: utf-8 -*-
"""BBA买车推荐 mock 脚本。"""
import re
from typing import Any, Dict, List, Optional


_CARS = [
    {"brand": "奔驰", "series": "奔驰A级", "price": "22万-27万", "min_price": 22, "max_price": 27, "car_type": "轿车", "reason": "入门豪华轿车，品牌感强，适合预算有限但想看奔驰的用户。"},
    {"brand": "奔驰", "series": "奔驰C级", "price": "33万-38万", "min_price": 33, "max_price": 38, "car_type": "轿车", "reason": "舒适性和豪华感均衡，适合日常通勤和家庭使用。"},
    {"brand": "奔驰", "series": "奔驰GLA", "price": "29万-34万", "min_price": 29, "max_price": 34, "car_type": "SUV", "reason": "尺寸灵活，适合城市代步和轻度家庭出行。"},
    {"brand": "奔驰", "series": "奔驰GLC", "price": "42万-53万", "min_price": 42, "max_price": 53, "car_type": "SUV", "reason": "空间和舒适性表现更完整，适合预算较高的家庭用户。"},
    {"brand": "奔驰", "series": "奔驰V级", "price": "50万-65万", "min_price": 50, "max_price": 65, "car_type": "MPV", "reason": "乘坐空间宽裕，适合多人出行或商务接待。"},
    {"brand": "宝马", "series": "宝马3系", "price": "31万-39万", "min_price": 31, "max_price": 39, "car_type": "轿车", "reason": "操控体验突出，适合重视驾驶感的用户。"},
    {"brand": "宝马", "series": "宝马5系", "price": "44万-55万", "min_price": 44, "max_price": 55, "car_type": "轿车", "reason": "空间、动力和商务属性更强，适合中高预算用户。"},
    {"brand": "宝马", "series": "宝马X1", "price": "28万-34万", "min_price": 28, "max_price": 34, "car_type": "SUV", "reason": "入门豪华SUV，空间实用，价格门槛相对友好。"},
    {"brand": "宝马", "series": "宝马X3", "price": "40万-50万", "min_price": 40, "max_price": 50, "car_type": "SUV", "reason": "兼顾驾驶质感和家用空间，适合家庭升级。"},
    {"brand": "宝马", "series": "宝马2系多功能旅行车", "price": "26万-31万", "min_price": 26, "max_price": 31, "car_type": "MPV", "reason": "座舱灵活，适合对空间有要求但预算不高的用户。"},
    {"brand": "奥迪", "series": "奥迪A3", "price": "20万-26万", "min_price": 20, "max_price": 26, "car_type": "轿车", "reason": "价格门槛低，适合第一次购买豪华品牌的用户。"},
    {"brand": "奥迪", "series": "奥迪A4L", "price": "30万-38万", "min_price": 30, "max_price": 38, "car_type": "轿车", "reason": "空间和配置均衡，家用通勤都比较合适。"},
    {"brand": "奥迪", "series": "奥迪Q3", "price": "27万-33万", "min_price": 27, "max_price": 33, "car_type": "SUV", "reason": "城市SUV属性明显，适合年轻家庭和日常代步。"},
    {"brand": "奥迪", "series": "奥迪Q5L", "price": "39万-49万", "min_price": 39, "max_price": 49, "car_type": "SUV", "reason": "空间表现成熟，综合产品力稳定，适合家用。"},
    {"brand": "奥迪", "series": "奥迪Q6", "price": "46万-63万", "min_price": 46, "max_price": 63, "car_type": "MPV", "reason": "三排空间更实用，适合多人家庭出行。"},
]


def mock_recommend_cars(
    budget: Optional[str] = None,
    brand: Optional[str] = None,
    car_type: Optional[str] = None,
    content: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    budget_range = _parse_budget_range(budget)
    brands = _parse_brands(brand)
    normalized_type = _normalize_car_type(car_type)

    matched = [
        car for car in _CARS
        if car["brand"] in brands
        and (not normalized_type or car["car_type"] == normalized_type)
        and _match_budget(car, budget_range)
    ]

    fallback = [
        car for car in _CARS
        if car["brand"] in brands
        and (not normalized_type or car["car_type"] == normalized_type)
    ]

    return _format_result(matched or fallback)


def _parse_brands(brand: Optional[str]) -> List[str]:
    if not brand or brand in {"BBA", "都行", "三个都看看", "都可以"}:
        return ["奔驰", "宝马", "奥迪"]

    brands = [item for item in ["奔驰", "宝马", "奥迪"] if item in brand]
    return brands or ["奔驰", "宝马", "奥迪"]


def _normalize_car_type(car_type: Optional[str]) -> Optional[str]:
    if not car_type:
        return None
    text = str(car_type).upper()
    for item in ["SUV", "MPV"]:
        if item in text:
            return item
    if "轿" in text:
        return "轿车"
    return None


def _parse_budget_range(budget: Optional[str]) -> Optional[Dict[str, float]]:
    if not budget:
        return None

    text = re.sub(r"\s+", "", str(budget))
    range_match = re.search(r"(\d+(?:\.\d+)?)万?(?:到|-|~|至)(\d+(?:\.\d+)?)万?", text)
    if range_match:
        low = float(range_match.group(1))
        high = float(range_match.group(2))
        return {"min": min(low, high), "max": max(low, high)}

    number_match = re.search(r"\d+(?:\.\d+)?", text)
    if not number_match:
        return None

    value = float(number_match.group(0))
    if any(word in text for word in ["以内", "以下", "不超过", "内"]):
        return {"min": 0, "max": value}
    if any(word in text for word in ["以上", "起", "不低于"]):
        return {"min": value, "max": 999}
    return {"min": max(0, value - 5), "max": value + 5}


def _match_budget(car: Dict[str, Any], budget_range: Optional[Dict[str, float]]) -> bool:
    if not budget_range:
        return True
    return car["min_price"] <= budget_range["max"] and car["max_price"] >= budget_range["min"]


def _format_result(cars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "brand": car["brand"],
            "series": car["series"],
            "price": car["price"],
            "car_type": car["car_type"],
            "reason": car["reason"],
        }
        for car in cars[:5]
    ]

# 只检测LOCAL_TOOLS或TOOLS注册的工具
LOCAL_TOOLS = [mock_recommend_cars]

