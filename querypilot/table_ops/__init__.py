"""元数据运维层（logs/08 §四）：新表自助接入的候选发现与问卷支撑。

零侵入保证：本包单向依赖现有包（metadata_engine / db），
不被任何运行时模块（ask / loader / pruner）反向引用。
"""
