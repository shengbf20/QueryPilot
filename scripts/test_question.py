"""测试单个问题的脚本"""
import sys
import os

# 设置标准输出编码为 UTF-8
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加项目根目录到 Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from querypilot.agent.pipeline import ask

def test_question(question: str, config: str = "full"):
    """测试单个问题

    Args:
        question: 自然语言问题
        config: 配置选项 - full/no_fix_sql/no_l1/no_l2/minimal
    """
    configs = {
        "full": dict(fix_sql=True, l1_enabled=True, l2_enabled=True),
        "no_fix_sql": dict(fix_sql=False, l1_enabled=True, l2_enabled=True),
        "no_l1": dict(fix_sql=True, l1_enabled=False, l2_enabled=True),
        "no_l2": dict(fix_sql=True, l1_enabled=True, l2_enabled=False),
        "minimal": dict(fix_sql=False, l1_enabled=False, l2_enabled=False),
    }

    if config not in configs:
        print(f"未知配置: {config}")
        print(f"可选配置: {', '.join(configs.keys())}")
        return

    print(f"问题: {question}")
    print(f"配置: {config}")
    print("-" * 50)

    try:
        result = ask(question, use_cache=False, **configs[config])

        print(f"生成的 SQL:")
        print(f"  {result.sql}")
        print()

        if result.rows:
            print(f"查询结果 (前5行):")
            for i, row in enumerate(result.rows[:5]):
                print(f"  {i+1}. {row}")
            if len(result.rows) > 5:
                print(f"  ... 共 {len(result.rows)} 行")
        else:
            print("查询结果: 无数据")

        print()
        print(f"是否修正: corrected={result.corrected}")

    except Exception as e:
        print(f"执行失败: {type(e).__name__}: {e}")


if __name__ == "__main__":
    # 默认测试问题
    question = "持有华泰紫金天天发货币市场基金且市值超过1000元的客户有多少人？"
    config = "full"

    # 从命令行参数获取
    if len(sys.argv) > 1:
        question = sys.argv[1]
    if len(sys.argv) > 2:
        config = sys.argv[2]

    test_question(question, config)
