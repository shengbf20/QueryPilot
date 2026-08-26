"""Question-level intent fence: refuse destructive / jailbreak instructions."""

from __future__ import annotations

import re

# First matching rule wins. Patterns target malicious *instructions*, not
# normal marketing filters (e.g. 账户状态为「销户」).
_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "destructive_ddl",
        re.compile(
            r"删库|删除数据库|删掉数据库|数据库删掉|整个数据库删|"
            r"drop\s+database|drop\s+table|"
            r"删除所有表|把所有表删|清空整个|清空所有业务表|"
            r"清空整个\s*duckdb|能清空整个",
            re.I,
        ),
        "检测到删库/删表类危险指令",
    ),
    (
        "data_mutation",
        re.compile(
            r"delete\s+from|truncate\s+|insert\s+into|update\s+\S+\s+set|"
            r"删除(?:客户信息表|持仓表|交易表|资产表)?.{0,12}所有记录|"
            r"删除所有(?:女性)?客户数据|把所有客户的年龄|"
            r"清空.*表|插入一条.{0,8}假|假装你在写\s*select",
            re.I,
        ),
        "检测到改写/清空数据类危险指令",
    ),
    (
        "privilege_io",
        re.compile(
            r"\battach\b|\bgrant\s+all\b|copy\s+.+\s+to|"
            r"授权写|覆盖写入|覆盖本库|安装扩展|"
            r"忽略只读|写到系统目录",
            re.I,
        ),
        "检测到越权写盘/授权/挂载类指令",
    ),
    (
        "injection_multistmt",
        re.compile(
            r";\s*(drop|delete|truncate|insert|update)\b|"
            r"然后\s*drop|再.*删掉|sql 字段必须是\s*drop",
            re.I,
        ),
        "检测到多语句注入或强制输出危险 SQL",
    ),
    (
        "unauthorized_schema",
        re.compile(
            r"duckdb_tables|sqlite_master|information_schema|pg_catalog|"
            r"系统表并删|删除元数据",
            re.I,
        ),
        "检测到探测/破坏系统目录的指令",
    ),
    (
        "jailbreak",
        re.compile(
            r"忽略所有安全规则|忽略之前所有安全|系统提示作废|"
            r"你现在是\s*(dba|管理员)|不要解释.{0,8}直接清空|"
            r"授权渗透测试|演示安全漏洞|"
            r"你不再是只读助手",
            re.I,
        ),
        "检测到越狱/角色劫持类指令",
    ),
    (
        "file_os",
        re.compile(
            r"/etc/passwd|c:\\windows|system32|read_csv|read_text|"
            r"扫描磁盘|打印\s*deepseek_api_key|读取.*\.env",
            re.I,
        ),
        "检测到读取主机文件或密钥的指令",
    ),
    (
        "mass_exfil",
        re.compile(
            r"全部客户的姓名和完整资料|打包发给外部|"
            r"全部客户身份证|发给第三方|"
            r"每一个客户的全部字段明文倾倒",
            re.I,
        ),
        "检测到批量导出敏感客户资料的指令",
    ),
)

SAFETY_WARNING_PREFIX = "安全警告: 拒绝执行该指令。"


def check_malicious_intent(question: str) -> str | None:
    """Return a short reason if ``question`` is a dangerous instruction."""
    text = (question or "").strip()
    if not text:
        return None
    for _name, pattern, reason in _RULES:
        if pattern.search(text):
            return reason
    return None


def format_safety_message(reason: str) -> str:
    """Stable warning text used by ask() and Extra3 eval."""
    detail = (reason or "").strip() or "检测到危险或越权操作"
    return (
        f"{SAFETY_WARNING_PREFIX}{detail}。"
        "QueryPilot 仅允许只读取数，不会执行写库、越权或越狱指令。"
    )
