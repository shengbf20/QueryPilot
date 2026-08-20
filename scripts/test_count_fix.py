"""测试 COUNT 格式错误检测和 L2 修正功能"""
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


def test_count_fix(question: str, runs: int = 5):
    """测试 COUNT 格式错误检测和 L2 修正

    Args:
        question: 自然语言问题
        runs: 运行次数
    """
    print(f"问题: {question}")
    print(f"运行次数: {runs}")
    print("=" * 60)

    results = []
    for i in range(runs):
        result = ask(question, use_cache=False, fix_sql=True, l1_enabled=True, l2_enabled=True)
        results.append(result)

        has_group_by = 'GROUP BY' in result.sql.upper() and 'COUNT' in result.sql.upper()
        print(f"\n运行 {i+1}:")
        print(f"  行数: {result.row_count}")
        print(f"  有GROUP BY: {has_group_by}")
        print(f"  是否修正: {result.corrected}")
        print(f"  结果: {result.rows[:3] if result.rows else '无结果'}")

    # 统计
    print("\n" + "=" * 60)
    print("统计:")
    corrected_count = sum(1 for r in results if r.corrected)
    print(f"  触发修正次数: {corrected_count}/{runs}")

    # 检查结果一致性
    result_values = [r.rows[0][0] if r.rows else None for r in results]
    unique_values = set(result_values)
    print(f"  结果值: {unique_values}")
    if len(unique_values) == 1:
        print(f"  结果一致性: 通过")
    else:
        print(f"  结果一致性: 不通过（LLM 随机性导致）")


if __name__ == "__main__":
    # 默认测试问题
    question = "持有华泰紫金天天发货币市场基金且市值超过1000元的客户有多少人？"

    # 从命令行参数获取
    if len(sys.argv) > 1:
        question = sys.argv[1]

    test_count_fix(question)
