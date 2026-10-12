# -*- coding: utf-8 -*-
"""账号绑定(一机一号)

2026-10-11 改: 首次登录成功后, 账号锁死在这台机器上。之后每次启动自动沿用保存的
登录态, 账号不可更换。手机上改了密码 -> 本地保存的密码失效 -> 只开放"更新密码"
入口, 账号仍然是锁死的那个。

绑定文件 = 程序目录下的 account.json(和 cookies.txt 同级)。
解绑的唯一方式: 删掉这个文件。

安全边界(别自欺欺人):
  - 密码用内置固定密钥做 AES, 只是不让明文出现在文件里, 挡不住逆向
  - 机器码挡的是"整个文件夹拷给别人接着用", 挡不住改注册表 / 改代码
  这层做的是把随手换号的成本抬高, 真正的授权校验在 license 那边。
"""
import json
import os
import tempfile
import threading
from datetime import datetime

from loguru import logger

from api.cipher import AESCipher
from api.config import GlobalConst as gc
from api.device import get_machine_code, get_machine_id

BINDING_VERSION = 1

STATUS_UNBOUND = "unbound"  # 还没绑过
STATUS_BOUND = "bound"  # 已绑且机器对得上
STATUS_FOREIGN = "foreign"  # 已绑但机器对不上(文件是从别的电脑拷来的)

_lock = threading.RLock()


class BindingError(Exception):
    """绑定相关错误的基类"""


class MachineMismatch(BindingError):
    """绑定文件属于另一台机器"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class AccountBinding:
    def __init__(self, path: str = None):
        self.path = path or gc.BINDING_PATH
        self._data: dict = {}
        self.status: str = STATUS_UNBOUND

    # ---------------------------------------------------------------- 读
    def load(self) -> "AccountBinding":
        """读盘。文件不存在/损坏/字段缺失一律视为未绑定, 不抛异常。"""
        with _lock:
            self._data = {}
            self.status = STATUS_UNBOUND

            if not os.path.isfile(self.path):
                return self

            try:
                with open(self.path, "r", encoding="utf8") as fp:
                    data = json.load(fp)
            except Exception as e:
                logger.warning(f"账号绑定文件读不出来({e}), 按未绑定处理: {self.path}")
                return self

            if not isinstance(data, dict) or not str(data.get("username", "") or "").strip():
                logger.warning(f"账号绑定文件内容无效, 按未绑定处理: {self.path}")
                return self
            if int(data.get("version", 0) or 0) > BINDING_VERSION:
                logger.warning("账号绑定文件来自更新版本的程序, 按未绑定处理")
                return self

            self._data = data

            saved_mid = str(self._data.get("machine_id", "") or "").strip()
            if not saved_mid:
                logger.warning("账号绑定文件缺少机器信息, 按未绑定处理")
                self._data = {}
                return self
            if saved_mid != get_machine_id():
                self.status = STATUS_FOREIGN
                return self

            self.status = STATUS_BOUND
            return self

    @property
    def is_bound(self) -> bool:
        return self.status == STATUS_BOUND

    @property
    def username(self) -> str:
        return str(self._data.get("username", "") or "").strip()

    @property
    def password(self) -> str:
        """解密后的密码, 拿不到返回空串(让上层走"重新输入密码"分支)。"""
        raw = str(self._data.get("password", "") or "")
        if not raw:
            return ""
        try:
            return AESCipher().decrypt(raw)
        except Exception as e:
            logger.warning(f"保存的密码解不开({e}), 需要重新输入")
            return ""

    @property
    def uid(self) -> str:
        return str(self._data.get("uid", "") or "").strip()

    @property
    def realname(self) -> str:
        return str(self._data.get("realname", "") or "").strip()

    @property
    def machine_code(self) -> str:
        return str(self._data.get("machine_code", "") or "").strip()

    @property
    def bound_at(self) -> str:
        return str(self._data.get("bound_at", "") or "").strip()

    @property
    def last_login(self) -> str:
        return str(self._data.get("last_login", "") or "").strip()

    def require_machine(self) -> None:
        """机器对不上直接抛, 由上层决定怎么提示。"""
        if self.status == STATUS_FOREIGN:
            raise MachineMismatch(
                f"本机的账号绑定文件来自另一台电脑(文件机器码 {self.machine_code or '未知'}, "
                f"本机 {get_machine_code()})"
            )

    def describe(self) -> str:
        """给界面用的一行描述。"""
        if not self._data:
            return "未绑定账号"
        who = self.username
        if self.realname:
            who += f"（{self.realname}）"
        extra = f"  绑定于 {self.bound_at}" if self.bound_at else ""
        return f"{who}{extra}  机器码 {self.machine_code or '未知'}"

    # ---------------------------------------------------------------- 写
    def bind(self, username: str, password: str, uid: str = "", realname: str = "") -> None:
        """账号锁死: 只在首次登录成功后调用一次。"""
        with _lock:
            self._data = {
                "version": BINDING_VERSION,
                "username": str(username).strip(),
                "password": AESCipher().encrypt(password) if password else "",
                "uid": str(uid or ""),
                "realname": str(realname or ""),
                "machine_id": get_machine_id(),
                "machine_code": get_machine_code(),
                "bound_at": _now(),
                "last_login": _now(),
            }
            self.status = STATUS_BOUND
            self._write()
            logger.info(f"账号已绑定本机: {self.username}")

    def update_password(self, password: str) -> None:
        """只改密码, 账号/机器信息一律不动。"""
        with _lock:
            if not self._data:
                raise BindingError("尚未绑定账号, 无法更新密码")
            self._data["password"] = AESCipher().encrypt(password) if password else ""
            self._write()
            logger.info(f"已更新本地保存的密码: {self.username}")

    def touch_login(self, uid: str = "", realname: str = "") -> None:
        """登录成功后刷新元信息(补 uid / 姓名 / 时间)。"""
        with _lock:
            if not self._data:
                return
            if uid and not self._data.get("uid"):
                self._data["uid"] = str(uid)
            if realname and self._data.get("realname") != realname:
                self._data["realname"] = str(realname)
            self._data["last_login"] = _now()
            self._write()

    def clear(self) -> None:
        """解绑。删文件即可, 没有单独入口, 由开发者掌握。"""
        with _lock:
            try:
                os.remove(self.path)
            except FileNotFoundError:
                pass
            self._data = {}
            self.status = STATUS_UNBOUND

    def _write(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".account-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf8") as fp:
                json.dump(self._data, fp, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
