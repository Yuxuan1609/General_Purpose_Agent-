from __future__ import annotations
from abc import ABC, abstractmethod

from capability import Capability, CapabilityResult


# ── Knowledge Store ──────────────────────────────────────────────────────

class BaseKnowledgeStore(ABC):
    """Abstract static knowledge storage.

    Implementations: in-memory dict, JSON files, vector DB, Elasticsearch, etc.
    Independent of L2 FlexibleKnowledge — L2 is dynamic experience,
    Knowledge is static reference.
    """

    @abstractmethod
    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Semantic/keyword search.

        Returns:
            list of {id, content, metadata, score}
        """
        ...

    @abstractmethod
    def get(self, doc_id: str) -> dict | None:
        """Exact lookup by ID. Returns None if not found."""
        ...

    @abstractmethod
    def add(self, doc_id: str, content: str, metadata: dict | None = None) -> None:
        """Add or overwrite a document."""
        ...

    @abstractmethod
    def remove(self, doc_id: str) -> bool:
        """Remove a document. Returns False if not found."""
        ...

    @abstractmethod
    def list_ids(self) -> list[str]:
        """Return all document IDs."""
        ...


class InMemoryKnowledgeStore(BaseKnowledgeStore):
    """Simple in-memory keyword-match store.

    Future replacements: ChromaDB, FAISS, Elasticsearch.
    """

    def __init__(self):
        self._docs: dict[str, dict] = {}

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        keywords = query.lower().split()
        scored = []
        for doc_id, doc in self._docs.items():
            content_lower = doc["content"].lower()
            score = sum(1 for kw in keywords if kw in content_lower)
            if score > 0:
                scored.append({
                    "id": doc_id,
                    "content": doc["content"],
                    "metadata": doc.get("metadata", {}),
                    "score": score,
                })
        scored.sort(key=lambda d: d["score"], reverse=True)
        return scored[:top_k]

    def get(self, doc_id: str) -> dict | None:
        doc = self._docs.get(doc_id)
        if doc is None:
            return None
        return {"id": doc_id, "content": doc["content"],
                "metadata": doc.get("metadata", {})}

    def add(self, doc_id: str, content: str,
            metadata: dict | None = None) -> None:
        self._docs[doc_id] = {
            "content": content,
            "metadata": metadata or {},
        }

    def remove(self, doc_id: str) -> bool:
        if doc_id not in self._docs:
            return False
        del self._docs[doc_id]
        return True

    def list_ids(self) -> list[str]:
        return list(self._docs.keys())

    def __len__(self) -> int:
        return len(self._docs)


# ── Knowledge Capability ─────────────────────────────────────────────────

class KnowledgeCapability(Capability):
    """Wraps KnowledgeStore instances as a Capability.

    Access control: per-store per-layer.
    Each store maps to a (BaseKnowledgeStore, set[visible_layers]) pair.

    Example:
        stores = {
            "game_rules": (store_a, {"l1", "l2", "l3"}),
            "api_docs":   (store_b, {"l3"}),
        }
    """

    name = "knowledge"

    def __init__(self, stores: dict[str, tuple[BaseKnowledgeStore, set[str]]]):
        self._stores = stores

    # ── Capability ABC ──────────────────────────────────────────────

    def is_visible_to(self, layer: str) -> bool:
        return any(layer in layers for _, layers in self._stores.values())

    def get_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "knowledge_query",
                "description": (
                    "Query static knowledge stores for reference information. "
                    "Returns matching documents with relevance scores."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "store": {
                            "type": "string",
                            "description": "Knowledge store to query",
                            "enum": list(self._stores.keys()),
                        },
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Max results (default 5)",
                        },
                    },
                    "required": ["store", "query"],
                },
            },
        }

    def invoke(self, layer: str, args: dict) -> CapabilityResult:
        store_name = args.get("store", "")
        query = args.get("query", "")
        top_k = int(args.get("top_k", 5))

        if store_name not in self._stores:
            return CapabilityResult(
                capability_name="knowledge", layer=layer, success=False,
                error=f"Unknown store: {store_name}",
            )

        store, visible_layers = self._stores[store_name]
        if layer not in visible_layers:
            return CapabilityResult(
                capability_name="knowledge", layer=layer, success=False,
                error=f"Store '{store_name}' not visible to layer '{layer}'",
            )

        try:
            results = store.search(query, top_k=top_k)
            return CapabilityResult(
                capability_name="knowledge", layer=layer, success=True,
                data=results,
            )
        except Exception as e:
            return CapabilityResult(
                capability_name="knowledge", layer=layer, success=False,
                error=str(e),
            )

    # ── public helpers ──────────────────────────────────────────────

    def visible_stores(self, layer: str) -> list[str]:
        return [
            name for name, (_, layers) in self._stores.items()
            if layer in layers
        ]


# ── Seed data ────────────────────────────────────────────────────────────

def seed_knowledge_stores() -> dict[str, InMemoryKnowledgeStore]:
    """Create seed knowledge stores for development and testing."""

    game_rules = InMemoryKnowledgeStore()
    game_rules.add("leduc_basics", (
        "Leduc Hold'em 简化版德州扑克：2人对局，6张牌（K/Q/J 各两种花色）。"
        "两轮下注：翻牌前和翻牌后，每轮最多2次加注。"
        "牌型比较：配对比单张高，同牌型比牌面大小和花色。"
        "行动：call / raise / fold / check。"
    ))
    game_rules.add("leduc_preflop", (
        "翻牌前策略："
        "持有K=强制加注（最强手牌，建立底池优势）；"
        "持有Q=根据对手行动跟注或加注（中等牌力）；"
        "持有J=通常弃牌或谨慎跟注（最弱手牌）。"
        "公共牌未翻时信息有限，应以牌面为唯一信号。"
    ))
    game_rules.add("leduc_postflop", (
        "翻牌后策略："
        "若手牌和公共牌配对→强力下注（已形成至少一对）；"
        "若手牌高于公共牌→可咋唬（对手可能无对）；"
        "若手牌低于公共牌→倾向于弃牌或便宜跟注。"
        "重点判断对手的下注模式：大注通常代表强牌。"
    ))

    design_docs = InMemoryKnowledgeStore()
    design_docs.add("a1_adjacent", (
        "A1: 层间严格相邻传递。"
        "L(0.5+1)↔L2↔L3，禁止跨层跳跃。"
        "相邻传递约束的是信息流向，不约束交互次数。"
    ))
    design_docs.add("a2_message", (
        "A2: 统一 LayerMessage 信封。"
        "六种基础类型：QUERY / RESPONSE / PROPOSAL / APPROVAL / REJECTION / NOTIFY。"
        "封装为独立模块 core/layer_message.py。"
    ))
    design_docs.add("a3_agents", (
        "A3: 层内 Agent 分工与信息隔离。"
        "每层包含 UpwardComm + DownwardComm + LayerManager。"
        "Comm Agent 是确定性协议处理，不涉及 LLM。"
        "每层只暴露相邻层需要的最小信息集。"
    ))
    design_docs.add("a4_learning", (
        "A4: 任务单元学习循环。"
        "以 Task 为最小执行和评估单元。"
        "Execute → Evaluate → Reflect & Learn。"
        "Reflect 已降级为 LearningEnv，与 GameEnv 平级。"
    ))

    return {"game_rules": game_rules, "design_docs": design_docs}
