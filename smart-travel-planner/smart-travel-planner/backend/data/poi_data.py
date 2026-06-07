"""
后端数据源池 - POI 点位数据 + UGC 点评

数据来源：模拟真实数据，MVP阶段聚焦郑州单城市。
后续可替换为真实 API 或向量数据库（RAG 知识库）。
"""

from typing import Optional

# ============================================
# POI 数据模型
# ============================================
class POI:
    def __init__(
        self,
        id: str,
        name: str,
        category: str,        # "景点" / "美食"
        sub_category: str,    # 自然风光/历史文化/网红打卡 / 火锅/小吃/西餐...
        lat: float,
        lng: float,
        district: str,        # 行政区划
        rating: float,        # 综合评分 1-5
        price_level: int,     # 人均消费档位 1-3 (低/中/高)
        price_avg: int,       # 人均消费(元)
        heat: int,            # 热度 0-100
        peak_wait_min: int,   # 高峰期预估排队时长(分钟)
        tags: list[str],      # 特色标签
        description: str,     # 简介
        best_time: str,       # 最佳游玩/用餐时段
    ):
        self.id = id
        self.name = name
        self.category = category
        self.sub_category = sub_category
        self.lat = lat
        self.lng = lng
        self.district = district
        self.rating = rating
        self.price_level = price_level
        self.price_avg = price_avg
        self.heat = heat
        self.peak_wait_min = peak_wait_min
        self.tags = tags
        self.description = description
        self.best_time = best_time

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "sub_category": self.sub_category,
            "lat": self.lat,
            "lng": self.lng,
            "district": self.district,
            "rating": self.rating,
            "price_level": self.price_level,
            "price_avg": self.price_avg,
            "heat": self.heat,
            "peak_wait_min": self.peak_wait_min,
            "tags": self.tags,
            "description": self.description,
            "best_time": self.best_time,
        }


# ============================================
# 郑州市 POI 数据池
# ============================================
ZHENGZHOU_POIS: list[POI] = [

    # ========== 景点 ==========
    POI("s001", "少林寺", "景点", "历史文化",
        34.5081, 112.9354, "登封市", 4.8, 2, 80, 95, 30,
        ["世界文化遗产", "功夫圣地", "禅宗祖庭"],
        "天下第一名刹，少林武术发源地", "08:00-10:00"),

    POI("s002", "二七纪念塔", "景点", "历史文化",
        34.7509, 113.6605, "二七区", 4.3, 1, 0, 70, 5,
        ["免费", "地标建筑", "红色旅游"],
        "郑州地标建筑，纪念京汉铁路工人大罢工", "09:00-16:00"),

    POI("s003", "河南博物院", "景点", "历史文化",
        34.7941, 113.6659, "金水区", 4.7, 1, 0, 85, 10,
        ["免费预约", "国宝云集", "贾湖骨笛"],
        "馆藏文物14万件，中华文明溯源必去", "09:00-11:00"),

    POI("s004", "郑州方特欢乐世界", "景点", "主题乐园",
        34.7236, 113.8858, "中牟县", 4.5, 3, 280, 90, 45,
        ["亲子", "过山车", "主题乐园"],
        "大型高科技主题乐园，适合家庭亲子游玩", "09:30开门"),

    POI("s005", "郑州动物园", "景点", "自然风光",
        34.7905, 113.6902, "金水区", 4.2, 1, 30, 70, 15,
        ["亲子", "熊猫", "休闲"],
        "城市中心的自然乐园，有国宝大熊猫", "09:00-11:00"),

    POI("s006", "黄河风景名胜区", "景点", "自然风光",
        34.9087, 113.5194, "惠济区", 4.4, 2, 60, 80, 20,
        ["黄河", "炎黄二帝像", "自然"],
        "登高望远观黄河，瞻仰炎黄二帝巨型塑像", "08:00-10:00"),

    POI("s007", "CBD如意湖", "景点", "网红打卡",
        34.7888, 113.7475, "郑东新区", 4.5, 1, 0, 85, 5,
        ["夜景", "拍照", "免费"],
        "郑东新区核心，大玉米楼灯光秀，夜游好去处", "18:00-21:00"),

    POI("s008", "郑州植物园", "景点", "自然风光",
        34.7611, 113.5311, "中原区", 4.3, 1, 20, 60, 10,
        ["植物", "亲子", "休闲"],
        "热带温室+蔷薇园，四季有花赏", "09:00-11:00"),

    POI("s009", "建业电影小镇", "景点", "网红打卡",
        34.7135, 113.8922, "中牟县", 4.3, 2, 100, 80, 20,
        ["电影", "拍照", "沉浸式"],
        "民国风情街+沉浸式戏剧体验，出片圣地", "14:00-17:00"),

    POI("s010", "登封嵩山", "景点", "自然风光",
        34.4911, 113.0412, "登封市", 4.6, 2, 80, 75, 25,
        ["五岳之一", "登山", "日出"],
        "中岳嵩山，登顶观日出，云海壮观", "05:00-08:00"),

    # ========== 美食 ==========
    POI("f001", "合记烩面馆(总店)", "美食", "本地特色",
        34.7532, 113.6535, "二七区", 4.5, 1, 35, 90, 40,
        ["郑州老字号", "烩面", "地道"],
        "百年老店，郑州烩面名片，汤浓面筋道", "11:00-13:00"),

    POI("f002", "萧记三鲜烩面美食城", "美食", "本地特色",
        34.7651, 113.6784, "管城区", 4.4, 1, 40, 80, 30,
        ["老字号", "三鲜烩面", "实惠"],
        "三鲜烩面开创者，汤清味鲜人尽皆知", "11:30-13:00"),

    POI("f003", "巴奴毛肚火锅(正弘城店)", "美食", "火锅",
        34.7939, 113.6812, "金水区", 4.6, 3, 150, 95, 60,
        ["毛肚", "产品主义", "网红"],
        "毛肚火锅开创者，食材新鲜服务好", "11:30-13:30"),

    POI("f004", "海底捞火锅(大卫城店)", "美食", "火锅",
        34.7558, 113.6597, "二七区", 4.4, 3, 130, 85, 50,
        ["服务好", "连锁", "深夜"],
        "极致服务体验，适合朋友聚会和庆生", "21:00-23:00"),

    POI("f005", "方中山胡辣汤(顺河路总店)", "美食", "本地特色",
        34.7612, 113.6835, "管城区", 4.6, 1, 15, 95, 45,
        ["胡辣汤", "早餐", "老字号"],
        "郑州早餐天花板，胡辣汤配油馍头绝配", "06:30-08:30"),

    POI("f006", "阿五黄河大鲤鱼(农业路店)", "美食", "豫菜",
        34.7918, 113.6729, "金水区", 4.5, 3, 120, 80, 30,
        ["黄河鲤鱼", "豫菜代表", "宴请"],
        "豫菜名片，红烧黄河大鲤鱼必点", "11:30-13:30"),

    POI("f007", "葛记焖饼(总店)", "美食", "本地特色",
        34.7574, 113.6630, "二七区", 4.3, 1, 25, 65, 15,
        ["百年老店", "焖饼", "实惠"],
        "郑州三记之一，焖饼配红豆粥绝了", "11:30-13:30"),

    POI("f008", "眷茶(正弘城店)", "美食", "饮品",
        34.7941, 113.6810, "金水区", 4.4, 2, 25, 75, 10,
        ["奶茶", "新式茶饮", "拍照"],
        "河南本土茶饮品牌，原创品类受欢迎", "14:00-17:00"),

    POI("f009", "彼酷哩烤全鱼(万象城店)", "美食", "川菜",
        34.7527, 113.6577, "二七区", 4.2, 2, 80, 75, 25,
        ["烤鱼", "聚餐", "辣"],
        "活鱼现烤，口味选择多，学生聚餐首选", "18:00-20:00"),

    POI("f010", "肯德基(二七万达店)", "美食", "快餐",
        34.7460, 113.6532, "二七区", 4.0, 2, 35, 50, 5,
        ["快餐", "炸鸡", "全国连锁"],
        "快速解决用餐，熟悉可靠的选择", "11:00-13:00"),

    POI("f011", "胖哥俩肉蟹煲(大卫城店)", "美食", "网红餐饮",
        34.7561, 113.6593, "二七区", 4.3, 2, 90, 80, 35,
        ["肉蟹煲", "网红", "聚餐"],
        "人气肉蟹煲，汤汁拌饭一绝", "18:00-20:00"),

    POI("f012", "郑州烤鸭总店", "美食", "豫菜",
        34.7615, 113.6803, "管城区", 4.4, 2, 70, 75, 20,
        ["烤鸭", "老字号", "豫菜"],
        "郑州本地烤鸭，皮脆肉嫩物美价廉", "11:30-13:30"),
]

# ============================================
# 行政区划地理数据
# ============================================
DISTRICT_BOUNDARIES = {
    "金水区":     {"lat": (34.78, 34.82), "lng": (113.65, 113.75)},
    "二七区":     {"lat": (34.72, 34.78), "lng": (113.62, 113.69)},
    "管城区":     {"lat": (34.72, 34.77), "lng": (113.66, 113.72)},
    "中原区":     {"lat": (34.73, 34.78), "lng": (113.56, 113.65)},
    "惠济区":     {"lat": (34.83, 34.93), "lng": (113.50, 113.66)},
    "郑东新区":   {"lat": (34.77, 34.82), "lng": (113.72, 113.78)},
    "中牟县":     {"lat": (34.68, 34.74), "lng": (113.85, 114.00)},
    "登封市":     {"lat": (34.40, 34.55), "lng": (112.85, 113.20)},
}


# ============================================
# 远距离区域（短时规划默认排除）
# ============================================
REMOTE_DISTRICTS = {"登封市"}

# ============================================
# 数据访问接口
# ============================================
def get_all_pois(exclude_remote: bool = False) -> list[POI]:
    """获取全量 POI 数据
    :param exclude_remote: 是否排除远距离区域（如登封市）
    """
    if exclude_remote:
        return [p for p in ZHENGZHOU_POIS if p.district not in REMOTE_DISTRICTS]
    return ZHENGZHOU_POIS


def filter_pois(
    category: Optional[str] = None,
    district: Optional[str] = None,
    max_price: Optional[int] = None,
    tags: Optional[list[str]] = None,
    min_rating: float = 0.0,
    exclude_remote: bool = False,
) -> list[POI]:
    """按条件筛选 POI"""
    results = ZHENGZHOU_POIS
    if exclude_remote:
        results = [p for p in results if p.district not in REMOTE_DISTRICTS]
    if category:
        results = [p for p in results if p.category == category]
    if district:
        results = [p for p in results if p.district == district]
    if max_price is not None:
        results = [p for p in results if p.price_avg <= max_price]
    if tags:
        results = [p for p in results if any(t in p.tags for t in tags)]
    if min_rating > 0:
        results = [p for p in results if p.rating >= min_rating]
    return results


def get_poi_by_id(poi_id: str) -> Optional[POI]:
    """按 ID 查询 POI"""
    for p in ZHENGZHOU_POIS:
        if p.id == poi_id:
            return p
    return None


def get_pois_by_ids(ids: list[str]) -> list[POI]:
    """批量查询 POI"""
    return [p for p in ZHENGZHOU_POIS if p.id in ids]
