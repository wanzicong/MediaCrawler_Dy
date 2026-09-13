"""配置基础设施：仓库根目录、相对路径字段清单与通用解析函数。"""

from pathlib import Path
from typing import Any

# 仓库根目录。本文件位于 modules/bootstrap/src/crawler/bootstrap/config/base.py，
# 仓库根在其上 6 层（config → bootstrap → crawler → src → bootstrap → modules → 仓库根）；
# **移动本文件必须同步调整层数**，否则 .env、相对路径与 config.yaml 都会解析失败。
# 无论进程从哪个工作目录启动，配置解析结果都必须保持一致。
BASE_DIR = Path(__file__).resolve().parents[6]

# 需要解析为绝对路径的相对路径配置项（统一拼接到仓库根目录下）
RELATIVE_PATH_FIELDS = (
    "DOUYIN_CDP_USER_DATA_DIR",
    "DOUYIN_LOCAL_CDP_USER_DATA_DIR",
    "DOUYIN_INTERACTION_SCREENSHOT_DIR",
    "MEDIA_OUTPUT_DIR",
)


def parse_cors(v: Any) -> list[str] | str:
    """解析 CORS 来源配置：兼容逗号分隔字符串与 JSON 列表两种写法。

    参数：
        v: 原始配置值，可为逗号分隔字符串、JSON 数组字符串或列表。

    返回：
        拆分后的来源列表，或原样返回的值（交由后续校验处理）。

    异常：
        ValueError: 值既不是字符串也不是列表时抛出。
    """
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)
