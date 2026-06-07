"""
RAG 检索增强引擎（轻量版）
- 字符级 n-gram 向量 + numpy 余弦相似度
- 零外部依赖，纯 Python + numpy
- 适合 MVP/黑客松演示：22 个 POI 检索
"""

import numpy as np
import re
from typing import Optional
from backend.data.poi_data import get_all_pois, POI


class LightweightRAG:
    """轻量级 RAG 引擎：字符 n-gram 向量 → 余弦相似度检索"""

    def __init__(self):
        self.pois: list[POI] = []
        self.vectors: np.ndarray | None = None
        self.poi_texts: list[str] = []
        self.vocab: dict[str, int] = {}  # char bigram → index
        self._built = False

    def _poi_to_text(self, poi: POI) -> str:
        """把 POI 转为可检索的文本"""
        return f"{poi.name} {poi.category} {poi.sub_category} {' '.join(poi.tags)} {poi.description} {poi.district}"

    def _tokenize(self, text: str) -> list[str]:
        """中文友好: 字符 bigram 分词"""
        # 保留中文、英文、数字
        text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', text).lower()
        tokens = []
        for i in range(len(text) - 1):
            tokens.append(text[i:i + 2])
        return tokens

    def build_index(self) -> int:
        """构建向量索引，返回索引 POI 数量"""
        self.pois = get_all_pois()
        self.poi_texts = [self._poi_to_text(p) for p in self.pois]

        # 构建词汇表（所有 bigram）
        all_tokens = set()
        for text in self.poi_texts:
            all_tokens.update(self._tokenize(text))
        self.vocab = {t: i for i, t in enumerate(sorted(all_tokens))}

        # 构建 POI 向量矩阵
        dim = len(self.vocab)
        self.vectors = np.zeros((len(self.pois), dim), dtype=np.float32)
        for i, text in enumerate(self.poi_texts):
            tokens = self._tokenize(text)
            for t in tokens:
                if t in self.vocab:
                    self.vectors[i, self.vocab[t]] += 1
            # L2 归一化
            norm = np.linalg.norm(self.vectors[i])
            if norm > 0:
                self.vectors[i] /= norm

        self._built = True
        return len(self.pois)

    def _query_to_vector(self, query: str) -> np.ndarray:
        """把查询转为同空间的向量"""
        vec = np.zeros(len(self.vocab), dtype=np.float32)
        tokens = self._tokenize(query)
        for t in tokens:
            if t in self.vocab:
                vec[self.vocab[t]] += 1
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    SIM_THRESHOLD = 0.15  # 低于此阈值触发降级

    def search(self, query: str, top_k: int = 5) -> dict:
        """
        向量检索：余弦相似度 top-k
        返回 {
            "results": [{poi_dict, score}, ...],
            "degraded": bool,
            "max_score": float,
            "search_log": {query, tokens, token_count, threshold, method}
        }
        """
        if not self._built:
            self.build_index()

        q_tokens = self._tokenize(query)
        q_vec = self._query_to_vector(query)

        search_log = {
            "query": query,
            "tokens": q_tokens[:30],  # 截断显示
            "token_count": len(q_tokens),
            "threshold": self.SIM_THRESHOLD,
            "method": "字符 bigram → 词表向量 → 余弦相似度",
        }

        if np.linalg.norm(q_vec) == 0:
            return {"results": [], "degraded": True, "max_score": 0.0, "search_log": search_log}

        # 批量计算余弦相似度
        scores = np.dot(self.vectors, q_vec)
        top_indices = np.argsort(-scores)[:top_k]

        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append({
                    "poi": self.pois[idx].to_dict(),
                    "score": round(float(scores[idx]), 4),
                })

        max_score = float(scores[top_indices[0]]) if len(results) > 0 else 0.0
        degraded = max_score < self.SIM_THRESHOLD

        return {
            "results": results,
            "degraded": degraded,
            "max_score": max_score,
            "search_log": search_log,
        }

    def format_context(self, query: str, top_k: int = 5) -> str:
        """构建 RAG 上下文：检索结果格式化为 LLM 提示词（含降级标记）"""
        search_result = self.search(query, top_k)
        results = search_result["results"]
        degraded = search_result["degraded"]

        if not results:
            return "（未检索到相关 POI）"

        prefix = ""
        if degraded:
            prefix = (
                "⚠️ 检索相似度较低（低于阈值），以下为地图通用推荐，"
                "仅供参考：\n\n"
            )

        lines = []
        for i, r in enumerate(results, 1):
            p = r["poi"]
            lines.append(
                f"{i}. [{p['category']}] {p['name']} | ⭐{p['rating']} | ¥{p['price_avg']} | "
                f"{p['district']} | 标签: {', '.join(p['tags'])} | {p['description']}"
            )
        return prefix + "\n".join(lines)


# 全局单例
_rag_instance: Optional[LightweightRAG] = None


def get_rag() -> LightweightRAG:
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = LightweightRAG()
        _rag_instance.build_index()
    return _rag_instance
