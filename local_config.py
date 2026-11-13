"""保存本机 DeepSeek 密钥，使用原子替换避免写入中断损坏配置。"""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


API_KEY_FILE = Path(__file__).resolve().parent / ".local" / "deepseek.json"


def read_api_key(path=API_KEY_FILE):
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        key = data.get("api_key") if isinstance(data, dict) else None
        if not isinstance(key, str) or not key.strip():
            raise ValueError()
        return key.strip()
    except (ValueError, UnicodeError):
        raise ValueError("本机密钥配置无效，请用 --save-api-key 重新输入并保存。") from None


def save_api_key(key, path=API_KEY_FILE):
    if not isinstance(key, str) or not key.strip():
        raise ValueError("API Key 不能为空。")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                prefix=".deepseek-", suffix=".tmp", delete=False) as file:
            temporary_path = Path(file.name)
            json.dump({"api_key": key.strip()}, file)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
