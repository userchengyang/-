# -*- coding: utf-8 -*-
"""机器指纹

用途: 把账号绑定文件锁死在当前这台电脑上。
把 account.json 原样复制到另一台机器会直接判定为无效, 防止客户把授权流转给别人。

取值优先级:
  1. Windows 注册表 MachineGuid —— 跟随 Windows 安装, 换硬盘/换网卡不变, 重装系统会变
  2. 兜底: 计算机名 + 网卡 MAC

输出一律是 sha256 摘要, 不落任何原始硬件信息。
"""
import hashlib
import platform
import uuid

_machine_id_cache = None


def _windows_machine_guid() -> str:
    """读取 HKLM\\SOFTWARE\\Microsoft\\Cryptography 的 MachineGuid."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            guid = str(value).strip()
            if guid:
                return guid
    except Exception:
        pass
    return ""


def raw_fingerprint() -> str:
    """拼出参与 hash 的原始串(仅用于排查, 不要写进任何文件)."""
    guid = _windows_machine_guid()
    if guid:
        return f"guid:{guid}"
    return f"node:{platform.node()}:{uuid.getnode()}"


def get_machine_id() -> str:
    """当前机器的稳定 ID, 32 位十六进制, 进程内缓存."""
    global _machine_id_cache
    if _machine_id_cache is None:
        _machine_id_cache = hashlib.sha256(
            raw_fingerprint().encode("utf-8")
        ).hexdigest()[:32]
    return _machine_id_cache


def get_machine_code() -> str:
    """给人看的短码, 形如 A1B2-C3D4-E5F6, 用于报错提示和客服核对."""
    mid = get_machine_id()
    return "-".join(mid[i : i + 4].upper() for i in range(0, 12, 4))
