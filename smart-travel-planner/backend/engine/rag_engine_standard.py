"""
RAG 检索增强引擎（标准版）
- jieba 中文分词 + TF-IDF 向量化（scikit-learn）
- 余弦相似度 → Top-K 检索 → LLM 增强生成
- 零模型下载，学术界经典 IR 基线

与轻量版对比：
  轻量版: 字符 bigram → 词表向量 → 余弦相似度
  标准版: jieba 分词 → TF-IDF 加权 → 余弦相似度（统计更科学）
"""

import numpy as np
from typing import Optional
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import jieba
from backend.data.poi_data import get_all_pois, POI


class StandardRAG:
    """标准 RAG 引擎：TF-IDF + 余弦相似度"""

    SIM_THRESHOLD = 0.10  # 低于此阈值触发降级

    def __init__(self):
        self.pois: list[POI] = []
        self.doc_texts: list[str] = []
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.vectors: Optional[np.ndarray] = None
        self._built = False

    def _poi_to_doc(self, poi: POI) -> str:
        """POI → 结构化文档文本"""
        tags_str = "、".join(poi.tags)
        return (
            f"名称：{poi.name}。"
            f"类型：{poi.category} {poi.sub_category}。"
            f"区域：{poi.district}。"
            f"标签：{tags_str}。"
            f"简介：{poi.description}。"
            f"适合：{poi.best_time}。"
        )

    def _jieba_cut(self, text: str) -> str:
        """jieba 分词后用空格连接，作为 TF-IDF 的 token"""
        return " ".join(jieba.cut(text))

    def build_index(self) -> int:
        """
        构建 TF-IDF 向量索引：
        1. jieba 中文分词
        2. TF-IDF 向量化（sklearn TfidfVectorizer）
        3. 存为稠密矩阵
        """
        self.pois = get_all_pois()
        raw_docs = [self._poi_to_doc(p) for p in self.pois]
        self.doc_texts = [self._jieba_cut(doc) for doc in raw_docs]

        self.vectorizer = TfidfVectorizer(
            analyzer="word",
            token_pattern=r"(?u)\b\w+\b",  # 匹配 jieba 分词后的 token
            max_features=200,               # 控制维度，避免稀疏
            ngram_range=(1, 2),             # 1-gram + 2-gram
        )
        self.vectors = self.vectorizer.fit_transform(self.doc_texts).toarray().astype(np.float32)
        # L2 归一化（余弦相似度）
        norms = np.linalg.norm(self.vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1
        self.vectors = self.vectors / norms

        self._built = True
        return len(self.pois)

    def search(self, query: str, top_k: int = 5) -> dict:
        """
        标准化检索：query → jieba 分词 → TF-IDF 向量 → 余弦相似度 top-k
        返回 {
            "results": [{poi_dict, score}, ...],
            "degraded": bool,
            "max_score": float,
            "search_log": {query, tokens, token_count, threshold, method}
        }
        """
        if not self._built:
            self.build_index()

        q_tokens_raw = list(jieba.cut(query))
        q_jieba = " ".join(q_tokens_raw)
        q_vec = self.vectorizer.transform([q_jieba]).toarray().astype(np.float32)
        q_norm = np.linalg.norm(q_vec)
        if q_norm > 0:
            q_vec = q_vec / q_norm

        search_log = {
            "query": query,
            "tokens": [t for t in q_tokens_raw if t.strip()][:30],  # 显示分词结果
            "token_count": len([t for t in q_tokens_raw if t.strip()]),
            "threshold": self.SIM_THRESHOLD,
            "method": "jieba 中文分词 → TF-IDF 统计加权 → 余弦相似度",
        }

        scores = np.dot(self.vectors, q_vec.T).flatten()
        top_indices = np.argsort(-scores)[:top_k]

        results = []
        for idx in top_indices:
            if scores[idx] > 0.001:
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
                f"{i}. [{p['category']}] {p['name']} | ⭐{p['rating']} | "
                f"¥{p['price_avg']} | {p['district']} | "
                f"标签: {', '.join(p['tags'])} | {p['description']}"
            )
        return prefix + "\n".join(lines)


# 全局单例
_standard_rag_instance: Optional[StandardRAG] = None


def get_standard_rag() -> StandardRAG:
    global _standard_rag_instance
    if _standard_rag_instance is None:
        _standard_rag_instance = StandardRAG()
        _standard_rag_instance.build_index()
    return _standard_rag_instance
