"""Benchmark 预定义任务集。

get_default_tasks() — 返回 10 个基准任务（5 数据分析 + 5 代码生成）。
get_adversarial_tasks() — 返回 7 个对抗任务（5 同任务多说法 + 2 模板外兜底）。
所有数据文件相对于 workspace/data/ 目录。
"""

from src.benchmark.models import BenchmarkTask


def get_default_tasks() -> list[BenchmarkTask]:
    """获取默认 benchmark 任务集（10 个）。

    5 个数据分析类 + 5 个代码生成类，覆盖项目全部核心能力。

    Returns:
        10 个 BenchmarkTask 的列表。
    """
    tasks: list[BenchmarkTask] = []

    # ── 数据分析类（5 个）────────────────────────────────────────────

    tasks.append(
        BenchmarkTask(
            id="BA-01",
            category="data_analysis",
            query="读取 sales.csv，统计 sales_volume 列的均值、中位数和标准差",
            expected_keywords=["sales", "均值", "标准差", "销量"],
            data_files=["sales.csv"],
        )
    )

    tasks.append(
        BenchmarkTask(
            id="BA-02",
            category="data_analysis",
            query="检查 sales.csv 的数据质量，报告缺失值、异常值和综合评分",
            expected_keywords=["缺失值", "异常值", "评分", "数据质量"],
            data_files=["sales.csv"],
        )
    )

    tasks.append(
        BenchmarkTask(
            id="BA-03",
            category="data_analysis",
            query="对 sales.csv 各区域销量画出柱状图，保存为 HTML 文件",
            expected_keywords=["图表", "bar", "bar_chart", "html"],
            data_files=["sales.csv"],
        )
    )

    tasks.append(
        BenchmarkTask(
            id="BA-04",
            category="data_analysis",
            query="用 run_text_to_sql 查询 sales.csv，统计每个区域（region）的平均销量",
            expected_keywords=["SELECT", "AVG", "region", "区域"],
            data_files=["sales.csv"],
        )
    )

    tasks.append(
        BenchmarkTask(
            id="BA-05",
            category="data_analysis",
            query="一键分析 inventory.csv 并生成完整报告",
            expected_keywords=["分析", "inventory", "报告"],
            data_files=["inventory.csv"],
        )
    )

    # ── 代码生成类（5 个）────────────────────────────────────────────

    tasks.append(
        BenchmarkTask(
            id="CG-01",
            category="code_generation",
            query="计算 EOQ：年需求 1000，订货成本 50，持有成本 2，打印结果",
            expected_keywords=["EOQ", "223", "inventory_eoq"],
        )
    )

    tasks.append(
        BenchmarkTask(
            id="CG-02",
            category="code_generation",
            query="使用 demand_forecast 模板预测未来 3 期需求：history=[100, 120, 110, 130, 125, 140]",
            expected_keywords=["预测", "MAPE", "forecasts"],
        )
    )

    tasks.append(
        BenchmarkTask(
            id="CG-03",
            category="code_generation",
            query="使用 safety_stock 模板计算安全库存：avg_demand=100, demand_std=20, lead_time=2, service_level=95%",
            expected_keywords=["安全库存", "Z", "1.64"],
        )
    )

    tasks.append(
        BenchmarkTask(
            id="CG-04",
            category="code_generation",
            query="使用 reorder_point 模板计算补货点：avg_demand=100, lead_time=2, safety_stock=50",
            expected_keywords=["补货点", "ROP", "reorder_point", "250"],
        )
    )

    tasks.append(
        BenchmarkTask(
            id="CG-05",
            category="code_generation",
            query="使用 inventory_pipeline 模板分析 sku_inventory.csv，订购成本 100，持有成本率 20%，单位成本 50，服务水平 95%，提前期 1",
            expected_keywords=["pipeline", "报告", "图表", "EOQ"],
            data_files=["sku_inventory.csv"],
        )
    )

    return tasks


def get_adversarial_tasks() -> list[BenchmarkTask]:
    """获取对抗任务集（7 个）——用于规则路由鲁棒性测试。

    5 个同任务多说法（测路由鲁棒性） + 2 个模板外任务（测 fallback 退化）。
    不修改 get_default_tasks()，独立函数。

    Returns:
        7 个 BenchmarkTask 的列表。
    """
    tasks: list[BenchmarkTask] = []

    # ── 同任务多说法 ×5（EOQ，测路由鲁棒性） ──

    tasks.append(
        BenchmarkTask(
            id="ADV-01",
            category="adversarial",
            query="年需求1000，订货成本50，持有成本2，帮我算EOQ",
            expected_keywords=["EOQ", "223"],
            timeout=30,
        )
    )

    tasks.append(
        BenchmarkTask(
            id="ADV-02",
            category="adversarial",
            query="每年要卖1000件，每次下单花50，存一年一件2块，最优订货量多少",
            expected_keywords=["EOQ", "223"],
            timeout=30,
        )
    )

    tasks.append(
        BenchmarkTask(
            id="ADV-03",
            category="adversarial",
            query="D=1000, S=50, H=2, 算一下经济订货批量",
            expected_keywords=["EOQ", "223"],
            timeout=30,
        )
    )

    tasks.append(
        BenchmarkTask(
            id="ADV-04",
            category="adversarial",
            query="帮我做个库存优化：年需求量一千，订货成本五十，单位持有成本二",
            expected_keywords=["EOQ", "223"],
            timeout=30,
        )
    )

    tasks.append(
        BenchmarkTask(
            id="ADV-05",
            category="adversarial",
            query="EOQ计算：annual_demand=1000, ordering_cost=50, holding_cost=2",
            expected_keywords=["EOQ", "223"],
            timeout=30,
        )
    )

    # ── 模板外任务 ×2（测 fallback 退化表现） ──

    tasks.append(
        BenchmarkTask(
            id="ADV-06",
            category="adversarial",
            query="写一个函数判断字符串是否为回文并测试",
            expected_keywords=["回文", "palindrome"],
            timeout=30,
        )
    )

    tasks.append(
        BenchmarkTask(
            id="ADV-07",
            category="adversarial",
            query="产品原价100元，打8折后参加满300减50，买3件最终多少钱，写代码计算",
            expected_keywords=["190", "最终"],
            timeout=30,
        )
    )

    return tasks
