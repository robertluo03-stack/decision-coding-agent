import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 导入你的planner（根据你的实际路径调整）
from src.agent.nodes.planner import run

# 测试用例集
test_cases = [
    {
        "name": "标准数据分析任务",
        "input": {
            "user_query": "读取data/sales.csv，统计每个sku的总销量，并画出柱状图",
            "workspace_path": "./src/workspace"
        },
        "expected_keywords": ["读取", "统计", "sku", "柱状图", "报告"]
    },
    {
        "name": "复杂优化任务",
        "input": {
            "user_query": "根据过去6个月的销售数据，预测未来30天需求，并计算每个SKU的安全库存和补货点",
            "workspace_path": "./src/workspace"
        },
        "expected_keywords": ["预测", "安全库存", "补货", "需求"]
    },
    {
        "name": "简单任务",
        "input": {
            "user_query": "读取data/inventory.csv，检查缺失值",
            "workspace_path": "./src/workspace"
        },
        "expected_keywords": ["读取", "缺失值", "检查"]
    },
    {
        "name": "边界情况-空输入",
        "input": {
            "user_query": "",
            "workspace_path": "./src/workspace"
        },
        "expected_keywords": []  # 应该返回错误提示或空列表
    },
    {
        "name": "边界情况-模糊需求",
        "input": {
            "user_query": "分析一下数据",
            "workspace_path": "./src/workspace"
        },
        "expected_keywords": ["分析", "数据"]
    }
]

def test_planner():
    print("=" * 60)
    print("Planner 节点测试")
    print("=" * 60)
    
    for i, case in enumerate(test_cases, 1):
        print(f"\n【测试 {i}】{case['name']}")
        print(f"输入: {case['input']['user_query'][:50]}...")
        
        try:
            # 调用planner
            result = run(case["input"])
            plan = result.get("plan", [])
            
            print(f"输出 plan: {plan}")
            print(f"步骤数: {len(plan)}")
            
            # 检查1：格式是否正确（必须是字符串列表）
            if not isinstance(plan, list):
                print("❌ 格式错误：plan不是列表")
                continue
                
            if not all(isinstance(p, str) for p in plan):
                print("❌ 格式错误：plan中包含非字符串元素")
                continue
            
            print("✅ 格式正确（List[str]）")
            
            # 检查2：步骤数是否合理（1-5步）
            if 1 <= len(plan) <= 5:
                print(f"✅ 步骤数合理（{len(plan)}步）")
            else:
                print(f"⚠️ 步骤数异常（{len(plan)}步），建议限制在5步以内")
            
            # 检查3：内容质量（是否包含关键词）
            plan_text = " ".join(plan)
            matched = [kw for kw in case["expected_keywords"] if kw in plan_text]
            if matched:
                print(f"✅ 内容相关（匹配关键词: {matched}）")
            else:
                print(f"⚠️ 内容相关性待验证（未匹配预期关键词）")
            
            # 检查4：步骤是否具体可执行（简单启发式）
            vague_words = ["分析", "处理", "优化", "看看"]
            vague_count = sum(1 for p in plan for w in vague_words if w in p and len(p) < 10)
            if vague_count > 2:
                print(f"⚠️ 存在{vague_count}个过于笼统的步骤，建议更具体")
            else:
                print("✅ 步骤较为具体")
                
        except Exception as e:
            print(f"❌ 执行报错: {type(e).__name__}: {e}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

if __name__ == "__main__":
    test_planner()