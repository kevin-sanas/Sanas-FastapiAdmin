"""把已授权使用的开发配置转换为 Compose raw env_file，不输出密钥、不覆盖文件。"""

import re
from pathlib import Path

from dotenv import dotenv_values


def main() -> None:
    directory = Path(__file__).resolve().parent
    target = directory / ".env.local"
    if target.exists():
        print("docker/.env.local 已存在，保留原配置。")
        return
    source = directory.parent / "backend" / "env" / ".env.dev"
    if not source.is_file():
        raise SystemExit("缺少 backend/env/.env.dev，请先配置现有数据库与 Redis。")
    values = dotenv_values(source)
    values["ENVIRONMENT"] = "prod"
    lines = []
    for key, value in values.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or value is None:
            raise SystemExit("配置包含不受支持的键或无值项，请人工检查源文件。")
        if "\n" in value or "\r" in value or "\0" in value:
            raise SystemExit("Compose raw 环境文件不支持本配置中的多行值。")
        lines.append(f"{key}={value}\n")
    with target.open("x", encoding="utf-8", newline="\n") as file:
        file.writelines(lines)
    print("已生成 docker/.env.local；保留现有数据库名称及凭据，不输出配置内容。")


if __name__ == "__main__":
    main()
