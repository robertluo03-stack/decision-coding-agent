"""领域优化模板层 — EOQ, 安全库存, 需求预测, 数据质量检测。"""

from src.domain.data_quality import run_quality_check

__all__ = ["run_quality_check"]
