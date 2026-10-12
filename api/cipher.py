# -*- coding:utf-8 -*-
"""登录参数加解密(学习通 passport 要求 uname/password 走 AES-CBC)

同时用于本地绑定文件保存密码 —— 注意: 密钥是程序内置的固定值,
只能防止密码以明文出现在文件里, 防不住有心逆向, 不要拿它当安全边界。
"""
import base64

import pyaes

from api.config import GlobalConst as gc


def pkcs7_unpadding(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    if not data:
        return data
    pad = data[-1]
    # 校验一下, 免得密钥不对时解出一堆乱码还当成功
    if pad < 1 or pad > 16 or len(data) < pad:
        raise ValueError("pkcs7 padding 非法, 可能密钥不匹配")
    for i in range(len(data) - pad, len(data)):
        if data[i] != pad:
            raise ValueError("pkcs7 padding 非法, 可能密钥不匹配")
    return data[: len(data) - pad]


def pkcs7_padding(s, block_size=16):
    if isinstance(s, str):
        s = s.encode("utf-8")
    pad = block_size - len(s) % block_size
    return s + bytes([pad]) * pad


def split_to_data_blocks(byte_str, block_size=16):
    length = len(byte_str)
    j, y = divmod(length, block_size)
    blocks = []
    shenyu = j * block_size
    for i in range(j):
        start = i * block_size
        end = start + block_size
        blocks.append(byte_str[start:end])
    if y:
        stext = byte_str[shenyu:]
        if stext:
            blocks.append(stext)
    return blocks


class AESCipher:
    def __init__(self):
        self.key = str(gc.AESKey).encode("utf8")
        self.iv = str(gc.AESKey).encode("utf8")

    def encrypt(self, plaintext: str) -> str:
        ciphertext = b""
        cbc = pyaes.AESModeOfOperationCBC(self.key, self.iv)
        plaintext = pkcs7_padding(plaintext)
        for b in split_to_data_blocks(plaintext):
            ciphertext = ciphertext + cbc.encrypt(b)
        return base64.b64encode(ciphertext).decode("utf8")

    def decrypt(self, ciphertext: str) -> str:
        cbc = pyaes.AESModeOfOperationCBC(self.key, self.iv)
        data = base64.b64decode(ciphertext)
        ptext = b""
        for b in split_to_data_blocks(data):
            ptext = ptext + cbc.decrypt(b)
        return pkcs7_unpadding(ptext).decode("utf-8")
