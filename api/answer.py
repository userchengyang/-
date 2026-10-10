import configparser
import json
import os
import random
import re
import shutil
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from re import sub
from typing import Optional

import httpx
from openai import OpenAI

from api.answer_check import check_answer
from api.logger import logger

__all__ = ["CacheDAO", "Tiku", "AI", "DummyTiku"]

# 项目根目录(不依赖启动时的工作目录)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CacheDAO:
    """
    @Author: SocialSisterYi
    @Reference: https://github.com/SocialSisterYi/xuexiaoyi-to-xuexitong-tampermonkey-proxy
    """
    DEFAULT_CACHE_FILE = os.path.join(PROJECT_ROOT, "cache.json")

    def __init__(self, file: str = DEFAULT_CACHE_FILE):
        self.cache_file = Path(file)
        self._lock = threading.RLock()
        if not self.cache_file.is_file():
            self._write_cache({})

    def _read_cache(self) -> dict:
        # 新增缓存文件读取的异常处理
        try:
            with self._lock:
                if not self.cache_file.is_file():
                    return {}
                try:
                    with self.cache_file.open("r", encoding="utf8") as fp:
                        return json.load(fp)
                except json.JSONDecodeError as e:
                    logger.error(f"缓存文件 JSON 解析失败: {e}, 尝试恢复...")
                    # 尝试从原始二进制中以 utf-8 忽略错误地恢复有效 JSON 段
                    recovered = self._recover_json_text()
                    if recovered is not None:
                        return recovered
                    # 若无法恢复，备份损坏文件并返回空缓存
                    self._backup_corrupt_cache()
                    return {}
                except UnicodeDecodeError as e:
                    logger.error(f"缓存文件编码读取失败: {e}, 采用恢复策略...")
                    recovered = self._recover_json_text()
                    if recovered is not None:
                        return recovered
                    self._backup_corrupt_cache()
                    return {}
        except Exception as e:
            logger.error(f"读取缓存异常: {e}")
            return {}

    def _recover_json_text(self) -> Optional[dict]:
        """从损坏文件中尽力恢复 JSON 内容."""
        try:
            raw = self.cache_file.read_bytes()
            text = raw.decode("utf-8", errors="ignore")
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1 and start < end:
                try:
                    return json.loads(text[start:end + 1])
                except Exception:
                    return None
        except Exception:
            return None
        return None

    def _backup_corrupt_cache(self) -> None:
        try:
            bak_name = f"{self.cache_file.name}.bak.{int(time.time())}"
            bak_path = self.cache_file.with_name(bak_name)
            shutil.copy2(self.cache_file, bak_path)
            logger.error(f"缓存文件已损坏，已备份为: {bak_path}，将使用空缓存继续运行")
        except Exception as ex:
            logger.error(f"备份损坏缓存失败: {ex}")

    def _write_cache(self, data: dict) -> None:
        # 为缓存写入加锁，防止并发写入损坏文件
        try:
            with self._lock:
                parent = self.cache_file.parent
                if not parent.exists():
                    parent.mkdir(parents=True, exist_ok=True)
                # 写入临时文件后原子替换，减少并发写入时的损坏风险
                fd, tmp_path = tempfile.mkstemp(prefix=self.cache_file.name, dir=str(parent))
                try:
                    with os.fdopen(fd, "w", encoding="utf8") as fp:
                        json.dump(data, fp, ensure_ascii=False, indent=4)
                        fp.flush()
                        os.fsync(fp.fileno())
                    os.replace(tmp_path, str(self.cache_file))
                except Exception as e:
                    # 清理临时文件
                    try:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except Exception:
                        pass
                    logger.error(f"Failed to write cache atomically: {e}")
        except IOError as e:
            logger.error(f"Failed to write cache: {e}")

    def get_cache(self, question: str) -> Optional[str]:
        data = self._read_cache()
        return data.get(question)

    def add_cache(self, question: str, answer: str) -> None:
        # 为缓存写入加锁，防止并发写入损坏文件
        with self._lock:
            data = self._read_cache()
            data[question] = answer
            self._write_cache(data)


class Tiku(ABC):
    CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.ini")
    DISABLE = False  # 停用标志
    SUBMIT = False  # 提交标志
    COVER_RATE = 0.8  # 覆盖率
    true_list = None
    false_list = None

    def __init__(self, config_path: Optional[str] = None) -> None:
        """
        初始化题库基类。

        Args:
            config_path: 配置文件路径，若为 None 则使用默认的 CONFIG_PATH。
        """
        self._name = None
        self._api = None
        self._conf = None
        self._config_path = config_path or self.CONFIG_PATH
        self.true_list = []
        self.false_list = []

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._name = value

    @property
    def api(self):
        return self._api

    @api.setter
    def api(self, value):
        self._api = value

    @property
    def token(self):
        return self._token

    @token.setter
    def token(self, value):
        self._token = value

    def init_tiku(self):
        # 仅用于题库初始化, 应该在题库载入后作初始化调用, 随后才可以使用题库
        # 尝试根据配置文件设置提交模式
        if not self._conf:
            self.config_set(self._get_conf())
        if not self.DISABLE:
            # 设置提交模式
            self.SUBMIT = True if self._conf['submit'] == 'true' else False
            self.COVER_RATE = float(self._conf['cover_rate'])
            self.true_list = self._conf['true_list'].split(',')
            self.false_list = self._conf['false_list'].split(',')
            # 调用自定义题库初始化
            self._init_tiku()

    def _init_tiku(self):
        # 仅用于题库初始化, 例如配置token, 交由自定义题库完成
        pass

    def config_set(self, config):
        self._conf = config

    def _get_conf(self):
        """
        从默认配置文件查询配置, 如果未能查到, 停用题库
        """
        try:
            config = configparser.ConfigParser(interpolation=None)
            config.read(self._config_path, encoding="utf8")
            return config['tiku']
        except (KeyError, FileNotFoundError):
            logger.info("未找到tiku配置, 已忽略题库功能")
            self.DISABLE = True
            return None

    @staticmethod
    def _conf_get(conf, key: str, default=None):
        """兼容 dict 与 configparser.SectionProxy 的取值."""
        if conf is None:
            return default
        if hasattr(conf, "get"):
            value = conf.get(key, default)
            return default if value is None else value
        return default

    @classmethod
    def _normalize_title(cls, q_info: dict) -> None:
        """预处理, 去除【单选题】、题号与分值这样与标题无关的字段"""
        logger.debug(f"原始标题：{q_info['title']}")
        q_info['title'] = sub(r'^\d+', '', q_info['title'])
        q_info['title'] = sub(r'（\d+\.\d+分）$', '', q_info['title'])
        logger.debug(f"处理后标题：{q_info['title']}")

    def query(self, q_info: dict) -> Optional[str]:
        if self.DISABLE:
            return None

        self._normalize_title(q_info)

        # 先过缓存（若存在章节检测错误反馈，说明处于重做模式，跳过缓存让大模型参考反馈重新作答）
        if not getattr(self, 'work_feedback', None):
            cached = CacheDAO().get_cache(q_info['title'])
            if cached:
                logger.info(f"从缓存中获取答案：{q_info['title']} -> {cached}")
                return cached.strip()

        answer = self._query(q_info)
        if not answer:
            logger.error(f"从{self.name}获取答案失败：{q_info['title']}")
            return None

        answer = answer.strip()
        logger.info(f"从{self.name}获取答案：{q_info['title']} -> {answer}")
        if check_answer(answer, q_info['type'], self):
            CacheDAO().add_cache(q_info['title'], answer)
            return answer
        logger.info(f"从{self.name}获取到的答案类型与题目类型不符，已舍弃")
        return None

    def query_all(self, q_list: list[dict], query_delay: float = 0.0) -> list[Optional[str]]:
        if self.DISABLE:
            return [None] * len(q_list)

        results = [None] * len(q_list)
        pending_indices = []

        cache_dao = CacheDAO()
        # 重做模式：不走缓存，让大模型参考错误反馈重新作答
        skip_cache = bool(getattr(self, 'work_feedback', None))
        for idx, q in enumerate(q_list):
            self._normalize_title(q)

            if skip_cache:
                pending_indices.append(idx)
                continue

            answer = cache_dao.get_cache(q['title'])
            if answer:
                logger.info(f"从缓存中获取答案：{q['title']} -> {answer}")
                results[idx] = answer.strip()
            else:
                pending_indices.append(idx)

        if not pending_indices:
            return results

        sub_q_list = [q_list[idx] for idx in pending_indices]
        sub_results = self._query_all(sub_q_list, query_delay=query_delay)

        if not isinstance(sub_results, list):
            logger.error(f"{self.name} _query_all 返回结果格式异常，期望列表")
            sub_results = [None] * len(pending_indices)
        elif len(sub_results) != len(pending_indices):
            logger.error(
                f"{self.name} _query_all 返回结果长度不匹配，期望 {len(pending_indices)}，实际 {len(sub_results)}")
            # 补齐或截断 sub_results 防止错位
            sub_results = list(sub_results) + [None] * (len(pending_indices) - len(sub_results))
            sub_results = sub_results[:len(pending_indices)]

        for idx, ans in zip(pending_indices, sub_results):
            q_info = q_list[idx]
            if ans:
                ans = ans.strip()
                logger.info(f"从{self.name}获取答案：{q_info['title']} -> {ans}")
                if check_answer(ans, q_info['type'], self):
                    cache_dao.add_cache(q_info['title'], ans)
                    results[idx] = ans
                else:
                    logger.info(f"从{self.name}获取到的答案类型与题目类型不符，已舍弃")
            else:
                logger.error(f"从{self.name}获取答案失败：{q_info['title']}")

        return results

    @abstractmethod
    def _query(self, q_info: dict) -> Optional[str]:
        """
        查询接口, 交由自定义题库实现
        """
        pass

    def set_work_feedback(self, feedback) -> None:
        """
        设置上一轮章节检测的错误反馈，供支持反馈的大模型题库在重新作答时参考。

        Args:
            feedback: 错误反馈，可以是 str 或 list[str]（描述哪些题目答错、正确答案是什么）
        """
        pass

    def _query_all(self, q_list: list[dict], query_delay: float = 0.0) -> list[Optional[str]]:
        """
        批量查询的实现接口，默认循环调用单个查询 _query。
        """
        results = []
        for q in q_list:
            if query_delay > 0:
                time.sleep(query_delay)
            try:
                results.append(self._query(q))
            except Exception as e:
                logger.error(f"{self.name} 查询单个题目发生异常: {e}")
                results.append(None)
        return results

    @staticmethod
    def get_tiku_from_config(config: Optional[dict] = None, config_path: Optional[str] = None):
        """
        从配置文件加载题库, 这个配置可以是用户提供, 可以是默认配置文件
        """
        conf = config
        path = config_path or Tiku.CONFIG_PATH
        if not conf:
            # 尝试从默认配置文件加载
            try:
                config_parser = configparser.ConfigParser(interpolation=None)
                config_parser.read(path, encoding="utf8")
                conf = config_parser['tiku']
            except (KeyError, FileNotFoundError):
                conf = None

        provider = str(Tiku._conf_get(conf, 'provider', '') or '').strip()
        if provider != 'AI':
            if conf is None:
                logger.error("未找到题库配置, 已忽略题库功能")
            else:
                logger.error(f"当前版本答题模块仅支持 AI, 无效的 provider: {provider!r}, 已忽略题库功能")
            return DummyTiku(config_path=path)

        new_cls = AI(config_path=path)
        new_cls.config_set(conf)
        return new_cls

    def judgement_select(self, answer: str) -> bool:
        """
        这是一个专用的方法, 要求配置维护两个选项列表, 一份用于正确选项, 一份用于错误选项, 以应对题库对判断题答案响应的各种可能的情况
        它的作用是将获取到的答案answer与可能的选项列对比并返回对应的布尔值
        """
        if self.DISABLE:
            return False
        # 对响应的答案作处理
        answer = answer.strip().lower()

        # 内置的高频通用判断词规整
        if answer in ['true', 't', '1', '对', '正确', '√', '是', 'yes', 'y']:
            return True
        if answer in ['false', 'f', '0', '错', '错误', '×', '否', 'no', 'n', '不对', '不正确']:
            return False

        # 兼容自定义配置列表
        if answer in [x.lower() for x in self.true_list] or answer in self.true_list:
            return True
        elif answer in [x.lower() for x in self.false_list] or answer in self.false_list:
            return False
        else:
            # 无法判断, 随机选择
            logger.error(
                f'无法判断答案 -> {answer} 对应的是正确还是错误, 请自行判断并加入配置文件重启脚本, 本次将会随机选择选项')
            return random.choice([True, False])

    def get_submit_params(self):
        """
        这是一个专用方法, 用于根据当前设置的提交模式, 响应对应的答题提交API中的pyFlag值
        """
        # 留空直接提交, 1保存但不提交
        if self.SUBMIT:
            return ""
        else:
            return "1"

    def check_llm_connection(self) -> bool:
        """
        检查大模型连接是否可用
        默认返回 True（非大模型题库不需要检查）
        """
        return True


class AI(Tiku):
    # AI大模型答题实现
    def __init__(self, config_path: Optional[str] = None) -> None:
        """初始化AI大模型答题实现."""
        super().__init__(config_path)
        self.name = 'AI大模型答题'
        self.last_request_time = None
        self._lock = threading.Lock()
        self.work_feedback = None  # 章节检测错误反馈（重做时参考）

    def set_work_feedback(self, feedback) -> None:
        """
        设置章节检测上一轮的错误反馈，供重新作答时参考。

        Args:
            feedback: str 或 list[str]，描述答错的题目与正确答案
        """
        self.work_feedback = feedback

    def _build_work_feedback_text(self) -> str:
        """将 work_feedback 转为提示词文本."""
        fb = self.work_feedback
        if not fb:
            return ""
        if isinstance(fb, str):
            return fb
        lines = [
            "你上一次作答的章节检测中有以下题目回答错误，"
            "请根据题目与正确答案仔细思考错因，纠正你的判断，本次作答务必保证每道题都正确："
        ]
        for item in fb:
            lines.append(str(item))
        return "\n".join(lines)

    def _is_deepseek_v4(self) -> bool:
        return (
                'api.deepseek.com' in (self.endpoint or '').lower()
                and (self.model or '').lower().startswith('deepseek-v4')
        )

    def _completion_kwargs(self, **kwargs):
        if self._is_deepseek_v4():
            # DeepSeek V4 defaults to thinking mode, which can leave message.content empty.
            kwargs['extra_body'] = {'thinking': {'type': 'disabled'}}
        return kwargs

    def _build_client(self) -> OpenAI:
        """构建 OpenAI 兼容客户端."""
        if self.http_proxy:
            httpx_client = httpx.Client(proxy=self.http_proxy)
            return OpenAI(http_client=httpx_client, base_url=self.endpoint, api_key=self.key)
        return OpenAI(base_url=self.endpoint, api_key=self.key)

    def _wait_for_interval(self):
        if self.last_request_time:
            interval_time = time.time() - self.last_request_time
            if interval_time < self.min_interval_seconds:
                sleep_time = self.min_interval_seconds - interval_time
                logger.debug(f"API请求间隔过短, 等待 {sleep_time} 秒")
                time.sleep(sleep_time)

    def _query(self, q_info: dict):
        with self._lock:
            return self._query_locked(q_info)

    def _query_locked(self, q_info: dict):
        def remove_md_json_wrapper(md_str):
            # 使用正则表达式匹配Markdown代码块并提取内容
            pattern = r'^\s*```(?:json)?\s*(.*?)\s*```\s*$'
            match = re.search(pattern, md_str, re.DOTALL)
            return match.group(1).strip() if match else md_str.strip()

        client = self._build_client()
        # 去除选项字母，防止大模型直接输出字母而非内容
        options_list = q_info['options'].split('\n')
        cleaned_options = [re.sub(r"^[A-Z]\s*", "", option) for option in options_list]
        options = "\n".join(cleaned_options)

        # 上一轮章节检测的错误反馈（若有）
        feedback_text = self._build_work_feedback_text()

        def _make_messages(system_content: str, user_content: str) -> list:
            """构造带反馈上下文的消息列表."""
            messages = [
                {
                    "role": "system",
                    "content": system_content
                },
            ]
            if feedback_text:
                messages.append(
                    {
                        "role": "system",
                        "content": feedback_text
                    }
                )
            messages.append(
                {
                    "role": "user",
                    "content": user_content
                }
            )
            return messages

        # 判断题目类型
        self._wait_for_interval()
        self.last_request_time = time.time()
        if q_info['type'] == "single":
            completion = client.chat.completions.create(**self._completion_kwargs(
                model=self.model,
                messages=_make_messages(
                    "本题为单选题，你只能选择一个选项，请根据题目和选项回答问题，以json格式输出正确的选项内容，示例回答：{\"Answer\": [\"答案\"]}。除此之外不要输出任何多余的内容，也不要使用MD语法。如果你使用了互联网搜索，也请不要返回搜索的结果和参考资料",
                    f"题目：{q_info['title']}\n选项：{options}"
                )
            ))
        elif q_info['type'] == 'multiple':
            completion = client.chat.completions.create(**self._completion_kwargs(
                model=self.model,
                messages=_make_messages(
                    "本题为多选题，你必须选择两个或以上选项，请根据题目和选项回答问题，以json格式输出正确的选项内容，示例回答：{\"Answer\": [\"答案1\",\n\"答案2\",\n\"答案3\"]}。除此之外不要输出任何多余的内容，也不要使用MD语法。如果你使用了互联网搜索，也请不要返回搜索的结果和参考资料",
                    f"题目：{q_info['title']}\n选项：{options}"
                )
            ))
        elif q_info['type'] == 'completion':
            completion = client.chat.completions.create(**self._completion_kwargs(
                model=self.model,
                messages=_make_messages(
                    "本题为填空题，你必须根据语境和相关知识填入合适的内容，请根据题目回答问题，以json格式输出正确的答案，示例回答：{\"Answer\": [\"答案\"]}。除此之外不要输出任何多余的内容，也不要使用MD语法。如果你使用了互联网搜索，也请不要返回搜索的结果和参考资料",
                    f"题目：{q_info['title']}"
                )
            ))
        elif q_info['type'] == 'judgement':
            completion = client.chat.completions.create(**self._completion_kwargs(
                model=self.model,
                messages=_make_messages(
                    "本题为判断题，你只能回答正确或者错误，请根据题目回答问题，以json格式输出正确的答案，示例回答：{\"Answer\": [\"正确\"]}。除此之外不要输出任何多余的内容，也不要使用MD语法。如果你使用了互联网搜索，也请不要返回搜索的结果和参考资料",
                    f"题目：{q_info['title']}"
                )
            ))
        else:
            completion = client.chat.completions.create(**self._completion_kwargs(
                model=self.model,
                messages=_make_messages(
                    "本题为简答题，你必须根据语境和相关知识填入合适的内容，请根据题目回答问题，以json格式输出正确的答案，示例回答：{\"Answer\": [\"这是我的答案\"]}。除此之外不要输出任何多余的内容，也不要使用MD语法。如果你使用了互联网搜索，也请不要返回搜索的结果和参考资料",
                    f"题目：{q_info['title']}"
                )
            ))

        try:
            response = json.loads(remove_md_json_wrapper(completion.choices[0].message.content))
            sep = "\n"
            return sep.join(response['Answer']).strip()
        except Exception:
            logger.error("无法解析大模型输出内容")
            return None

    def _init_tiku(self):
        self.endpoint = self._conf['endpoint'].strip().rstrip('/')
        self.key = self._conf['key'].strip()
        self.model = self._conf['model'].strip()
        self.http_proxy = str(self._conf.get('http_proxy', '') or '').strip()
        try:
            self.min_interval_seconds = float(self._conf.get('min_interval_seconds', 3) or 0)
        except (TypeError, ValueError):
            self.min_interval_seconds = 3.0

    def check_llm_connection(self) -> bool:
        """
        检查大模型连接是否可用
        发送一个简单的测试请求来验证 API 配置
        """
        with self._lock:
            logger.info(f'正在检查 {self.name} 连接...')
            try:
                client = self._build_client()

                # 限流等待
                self._wait_for_interval()
                self.last_request_time = time.time()

                # 发送测试请求
                completion = client.chat.completions.create(**self._completion_kwargs(
                    model=self.model,
                    messages=[
                        {
                            'role': 'user',
                            'content': '你好，请回答：1+1 等于几？只回答数字。'
                        }
                    ],
                    max_tokens=200  # 增大以支持可能返回的 reasoning_content
                ))

                # 统一检查响应
                if completion.choices:
                    msg = completion.choices[0].message
                    if msg.content or getattr(msg, 'reasoning_content', None):
                        logger.info(f'{self.name} 连接检查成功')
                        return True

                logger.error(f'{self.name} 连接检查失败：未收到响应')
                return False

            except Exception as e:
                logger.error(f'{self.name} 连接检查失败：{e}')
                return False


class DummyTiku(Tiku):
    def __init__(self, config_path: Optional[str] = None) -> None:
        """初始化空题库."""
        super().__init__(config_path)
        self.name = '空/禁用题库'
        self.DISABLE = True

    def _query(self, q_info: dict) -> Optional[str]:
        return None


PROVIDER_REGISTRY = {
    'AI': AI,
}
