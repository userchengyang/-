# -*- coding: utf-8 -*-
"""超星学习通刷课 CLI（核心刷课 + AI 答题）

运行流程:
  1. 读取 config.ini (答题AI必须在该文件中配置, 程序不提供配置向导)
  2. 输入账号密码登录
  3. 展示课程列表, 选择要刷的课程
  4. 并发执行任务点(视频/文档/章节检测/阅读/直播)

模式:
  python main.py                    # 默认: 读 config.ini, 交互输入账号密码
  python main.py -c config.ini      # 使用指定配置文件
  python main.py -u 账号 -p 密码     # 命令行参数
"""
import argparse
import configparser
import enum
import getpass
import os
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any

from tqdm import tqdm

from api.answer import Tiku
from api.base import Chaoxing, Account, StudyResult
from api.exceptions import LoginError, InputFormatError
from api.logger import logger
from api.live import Live
from api.live_process import LiveProcessor

try:
    from queue import PriorityQueue, ShutDown
except ImportError:
    from queue import PriorityQueue


    class ShutDown(Exception):
        pass


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")
CONFIG_TEMPLATE_PATH = os.path.join(BASE_DIR, "config_template.ini")

BANNER = """
============================================================
   超星学习通刷课 CLI   (核心刷课 + AI 答题)
============================================================
"""


class ChapterResult(enum.Enum):
    SUCCESS = 0,
    ERROR = 1,
    NOT_OPEN = 2,
    PENDING = 3


def log_error(func):
    def wrapper(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except BaseException as e:
            logger.error(f"Error in thread {threading.current_thread().name}: {e}")
            traceback.print_exception(type(e), e, e.__traceback__)
            raise

    return wrapper


def str_to_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


# ---------------------------------------------------------------------------
# 配置文件读写
# ---------------------------------------------------------------------------
def load_ini(path: str):
    """读取配置文件, 返回 (common_dict, tiku_dict), 文件不存在返回 ({}, {})."""
    if not path or not os.path.isfile(path):
        return {}, {}
    config = configparser.ConfigParser(interpolation=None)
    try:
        config.read(path, encoding="utf8")
    except Exception as e:
        logger.error(f"读取配置文件失败: {e}")
        return {}, {}

    common_config: dict[str, Any] = {}
    tiku_config: dict[str, Any] = {}

    if config.has_section("common"):
        common_config = dict(config.items("common"))
        if common_config.get("course_list"):
            common_config["course_list"] = [
                item.strip() for item in common_config["course_list"].split(",") if item.strip()
            ]
        else:
            common_config["course_list"] = None
        common_config["speed"] = float(common_config.get("speed", 1.0) or 1.0)
        common_config["jobs"] = int(common_config.get("jobs", 4) or 4)
        common_config["retry_interval"] = float(common_config.get("retry_interval", 1.0) or 1.0)
        common_config["work_max_retries"] = int(common_config.get("work_max_retries", 3) or 3)
        common_config["work_redo_enabled"] = str_to_bool(common_config.get("work_redo_enabled", False))
        common_config["use_cookies"] = str_to_bool(common_config.get("use_cookies", False))
        common_config.setdefault("notopen_action", "retry")

    if config.has_section("tiku"):
        tiku_config = dict(config.items("tiku"))

    return common_config, tiku_config


def save_ini(path: str, common_config: dict, tiku_config: dict) -> None:
    """写入配置文件(不含任何注释)."""
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str  # 保持键名大小写
    cp.add_section("common")
    for key, value in common_config.items():
        if value is None:
            value = ""
        elif isinstance(value, bool):
            value = "true" if value else "false"
        elif isinstance(value, list):
            value = ",".join(str(v) for v in value)
        cp.set("common", str(key), str(value))

    cp.add_section("tiku")
    for key, value in tiku_config.items():
        cp.set("tiku", str(key), "" if value is None else str(value))

    with open(path, "w", encoding="utf8") as fp:
        cp.write(fp)
    logger.info(f"配置已保存: {path}")


def strip_ini_comments(text: str) -> str:
    """去掉 ini 文本中的注释行与空行.

    原文件里紧跟字段的注释会被一并删除, 因此对每个 [section] 前补一个空行保持可读性。
    """
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith((";", "#")):
            continue
        if stripped.startswith("[") and out:
            out.append("")
        out.append(line.rstrip())
    return "\n".join(out) + "\n"


def ensure_config(path: str) -> bool:
    """确保 config.ini 存在.

    不存在时从 config_template.ini 复制一份并去掉全部注释。

    Returns:
        True 表示配置文件本就存在, False 表示本次刚生成(需要用户填写后重启)
    """
    if os.path.isfile(path):
        return True

    try:
        with open(CONFIG_TEMPLATE_PATH, "r", encoding="utf8") as fp:
            content = strip_ini_comments(fp.read())
        with open(path, "w", encoding="utf8") as fp:
            fp.write(content)
        logger.info(f"已根据模板生成配置文件: {path}")
    except OSError as e:
        logger.error(f"生成配置文件失败({e}), 将使用内置默认值")
        save_ini(path, default_common_config(), default_tiku_config())
    return False


def missing_tiku_fields(tiku_config: dict) -> list[str]:
    """返回 [tiku] 段中缺失的必填项(用于提示用户去配置文件补全)."""
    required = {
        "endpoint": "接口地址, 例如 https://api.deepseek.com/v1",
        "key": "API Key",
        "model": "模型名称, 例如 deepseek-chat",
    }
    return [f"{name} ({desc})" for name, desc in required.items()
            if not str(tiku_config.get(name, "") or "").strip()]


def tiku_config_hint() -> str:
    """答题AI未配置时给用户看的提示文本."""
    return (
        "\n"
        "  答题AI尚未配置, 请手动编辑配置文件后重新运行:\n"
        f"    {CONFIG_PATH}\n"
        "  需要填写 [tiku] 段的以下三项:\n"
        "    endpoint = 接口地址, 例如 https://api.deepseek.com/v1\n"
        "    key      = API Key, 例如 sk-xxxxxxxx\n"
        "    model    = 模型名称, 例如 deepseek-chat\n"
        "  (字段含义可参考同目录下的 config_template.ini)\n"
    )


def default_common_config() -> dict:
    return {
        "username": "",
        "password": "",
        "use_cookies": False,
        "course_list": None,
        "speed": 1.0,
        "jobs": 4,
        "notopen_action": "retry",
        "retry_interval": 1.0,
        "work_redo_enabled": False,
        "work_max_retries": 3,
    }


def default_tiku_config() -> dict:
    return {
        "provider": "AI",
        "check_llm_connection": "true",
        "submit": "true",
        "cover_rate": "0.8",
        "delay": "1.0",
        "endpoint": "",
        "key": "",
        "model": "",
        "min_interval_seconds": "1",
        "http_proxy": "",
        "true_list": "正确,对,√,是",
        "false_list": "错误,错,×,否,不对,不正确",
    }


# ---------------------------------------------------------------------------
# 题库(AI)工具
# ---------------------------------------------------------------------------
def create_tiku(tiku_config: dict, config_path: str = None) -> Tiku:
    """根据配置构建并初始化题库实例."""
    tiku = Tiku.get_tiku_from_config(dict(tiku_config), config_path=config_path or CONFIG_PATH)
    tiku.init_tiku()
    return tiku


def normalize_endpoint(raw: str) -> str:
    """把用户填写的地址规整为 OpenAI 兼容 base_url."""
    url = (raw or "").strip().rstrip("/")
    lowered = url.lower()
    for suffix in ("/chat/completions", "/v1/chat/completions"):
        if lowered.endswith(suffix):
            url = url[: -len(suffix)]
            break
    return url.rstrip("/")


# ---------------------------------------------------------------------------
# 交互输入工具
# ---------------------------------------------------------------------------
def ask(prompt_text: str, default: str = "", secret: bool = False) -> str:
    """读取一行输入, default 非空时回车即取默认值."""
    try:
        raw = getpass.getpass(prompt_text) if secret else input(prompt_text)
    except (EOFError, KeyboardInterrupt):
        print()
        raise
    raw = (raw or "").strip()
    if not raw:
        return default
    return raw


def wizard_account(common_config: dict) -> tuple[str, str, bool]:
    """步骤1: 输入账号密码, 返回 (账号, 密码, 是否保存)."""
    print("\n[1/2] 账号登录")
    saved_user = str(common_config.get("username", "") or "").strip()
    saved_pwd = str(common_config.get("password", "") or "").strip()

    if saved_user:
        print(f"  检测到已保存账号: {saved_user}")
        if ask("  回车使用该账号, 输入 n 更换: ", default="").lower() == "n":
            saved_user = ""
            saved_pwd = ""

    username = saved_user or ask("  手机号账号: ")
    while not username:
        print("  \033[31m账号不能为空\033[0m")
        username = ask("  手机号账号: ")

    if saved_pwd and saved_user:
        password = saved_pwd
        print("  使用已保存的密码")
    else:
        password = ask("  登录密码: ", secret=True)
        while not password:
            print("  \033[31m密码不能为空\033[0m")
            password = ask("  登录密码: ", secret=True)

    save = bool(password) and ask("  是否记住账号密码到 config.ini? (Y/n): ", default="y").lower() != "n"
    return username, password, save


def wizard_runtime(common_config: dict) -> dict:
    """可选的运行参数, 直接回车使用默认值."""
    print("\n[2/2] 运行参数 (直接回车使用默认值)")
    speed = ask(f"  视频倍速 1~2 [{common_config.get('speed', 1.0)}]: ")
    jobs = ask(f"  同时进行的章节数 [{common_config.get('jobs', 4)}]: ")

    config = dict(common_config)
    try:
        config["speed"] = min(2.0, max(1.0, float(speed))) if speed else float(common_config.get("speed", 1.0))
    except ValueError:
        config["speed"] = 1.0
    try:
        config["jobs"] = max(1, int(jobs)) if jobs else int(common_config.get("jobs", 4))
    except ValueError:
        config["jobs"] = 4
    config.setdefault("notopen_action", "retry")
    config.setdefault("retry_interval", 1.0)
    config.setdefault("work_redo_enabled", False)
    config.setdefault("work_max_retries", 3)
    config.setdefault("use_cookies", False)
    return config


def login_with_retry(chaoxing: Chaoxing) -> None:
    """登录, 失败时允许重新输入账号密码."""
    while True:
        state = chaoxing.login(login_with_cookies=False)
        if state["status"]:
            return
        logger.error(f"登录失败: {state['msg']}")
        if ask("  重新输入账号密码? 回车重试, 输入 q 退出: ", default="").lower() == "q":
            raise LoginError(state["msg"])
        username = ask("  手机号账号: ")
        password = ask("  登录密码: ", secret=True)
        chaoxing.account = Account(username, password)


def select_courses(all_course: list[dict]) -> list[dict]:
    """展示课程列表并让用户选择."""
    if not all_course:
        raise RuntimeError("未读取到任何课程, 请检查账号")

    print("\n" + "=" * 20 + " 课程列表 " + "=" * 20)
    for idx, course in enumerate(all_course, 1):
        print(f"  [{idx}] {course['title']}")
        print(f"       courseId={course['courseId']} clazzId={course['clazzId']}")
    print("=" * 52)
    print("  提示: 同一 courseId 下若存在多个班级, 将分别完成")

    while True:
        raw = ask("  输入要刷的课程序号(逗号分隔), 回车=全部, q=退出: ", default="")
        if raw.lower() == "q":
            raise SystemExit(0)
        if not raw:
            return list(all_course)

        picked: list[dict] = []
        valid = True
        seen = set()
        for token in raw.replace("，", ",").split(","):
            token = token.strip()
            if not token:
                continue
            if not token.isdigit() or not (1 <= int(token) <= len(all_course)):
                print(f"  \033[31m无效序号: {token}\033[0m")
                valid = False
                break
            index = int(token)
            if index in seen:
                continue
            seen.add(index)
            picked.append(all_course[index - 1])
        if valid and picked:
            return picked
        if valid and not picked:
            print("  \033[31m未选择任何课程\033[0m")


# ---------------------------------------------------------------------------
# 任务执行
# ---------------------------------------------------------------------------
def process_job(chaoxing: Chaoxing, course: dict, job: dict, job_info: dict, speed: float) -> StudyResult:
    """处理单个任务点"""
    # 视频任务
    if job["type"] == "video":
        logger.trace(f"识别到视频任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
        # 超星的接口没有返回当前任务是否为Audio音频任务
        video_result = chaoxing.study_video(
            course, job, job_info, _speed=speed, _type="Video"
        )
        if video_result.is_failure():
            logger.warning("当前任务非视频任务, 正在尝试音频任务解码")
            video_result = chaoxing.study_video(
                course, job, job_info, _speed=speed, _type="Audio")
        if video_result.is_failure():
            logger.warning(
                f"出现异常任务 -> 任务章节: {course['title']} 任务ID: {job['jobid']}, 已跳过"
            )
        return video_result
    # 文档任务
    elif job["type"] == "document":
        logger.trace(f"识别到文档任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
        return chaoxing.study_document(course, job)
    # 测验任务
    elif job["type"] == "workid":
        logger.trace(f"识别到章节检测任务, 任务章节: {course['title']}")
        return chaoxing.study_work(course, job, job_info)
    # 阅读任务
    elif job["type"] == "read":
        logger.trace(f"识别到阅读任务, 任务章节: {course['title']}")
        return chaoxing.study_read(course, job, job_info)
    # 直播任务
    elif job["type"] == "live":
        logger.trace(f"识别到直播任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
        try:
            # 准备直播所需参数
            defaults = {
                "userid": chaoxing.get_uid(),
                "clazzId": course.get("clazzId"),
                "knowledgeid": job_info.get("knowledgeid")
            }

            # 创建直播对象
            live = Live(
                attachment=job,
                defaults=defaults,
                course_id=course.get("courseId")
            )

            # 启动直播处理线程
            thread = threading.Thread(
                target=LiveProcessor.run_live,
                args=(live, speed),
                daemon=True
            )
            thread.start()
            thread.join()  # 等待直播处理完成
            return StudyResult.SUCCESS
        except Exception as e:
            logger.error(f"处理直播任务时出错: {str(e)}")
            return StudyResult.ERROR

    logger.error(f"未知任务类型: {job['type']}")
    return StudyResult.ERROR


@dataclass
class ChapterTask:
    index: int
    point: dict[str, Any]
    course: dict[str, Any]
    result: ChapterResult = ChapterResult.PENDING
    tries: int = 0

    def __lt__(self, other):
        """比较两个任务的索引大小，用于优先级队列排序."""
        if not isinstance(other, ChapterTask):
            return NotImplemented
        return self.index < other.index


class JobProcessor:
    def __init__(self, chaoxing: Chaoxing, tasks: list[ChapterTask], config: dict[str, Any]):
        """初始化任务处理器."""
        if "jobs" not in config or not config["jobs"]:
            config["jobs"] = 4

        self.chaoxing = chaoxing
        self.speed = config["speed"]
        self.max_tries = 5
        self.tasks = tasks
        self.failed_tasks: list[ChapterTask] = []
        self.task_queue: PriorityQueue[ChapterTask] = PriorityQueue()
        self.retry_queue: PriorityQueue[ChapterTask] = PriorityQueue()
        self.wait_queue: PriorityQueue[ChapterTask] = PriorityQueue()
        self.threads: list[threading.Thread] = []
        self.worker_num = config["jobs"]
        self.config = config
        self.retry_interval = config.get("retry_interval", 1.0)

    def run(self):
        for task in self.tasks:
            self.task_queue.put(task)

        for i in range(self.worker_num):
            thread = threading.Thread(target=self.worker_thread, daemon=True)
            self.threads.append(thread)
            thread.start()

        threading.Thread(target=self.retry_thread, daemon=True).start()

        self.task_queue.join()
        time.sleep(0.5)
        if hasattr(self.task_queue, "shutdown"):
            self.task_queue.shutdown()

    @log_error
    def worker_thread(self):
        while True:
            try:
                task = self.task_queue.get()
            except ShutDown:
                logger.info("Queue shut down")
                return

            task.result = process_chapter(self.chaoxing, task.course, task.point, self.speed)

            match task.result:
                case ChapterResult.SUCCESS:
                    logger.debug("Task success: {} - {}", task.course["title"], task.point["title"])
                    self.task_queue.task_done()
                    logger.debug(f"unfinished task: {self.task_queue.unfinished_tasks}")

                case ChapterResult.NOT_OPEN:
                    if self.config["notopen_action"] == "continue":
                        logger.warning("章节未开启: {} - {}, 正在跳过", task.course["title"], task.point["title"])
                        self.task_queue.task_done()
                        continue

                    task.tries += 1
                    if task.tries >= self.max_tries:
                        logger.error(
                            "章节未开启: {} - {} 可能由于上一章节的章节检测未完成, 也可能由于该章节因为时效已关闭，"
                            "请手动检查完成并提交再重试。或者在配置中配置(自动跳过关闭章节/开启题库并启用提交)"
                            , task.course["title"], task.point["title"])
                        self.task_queue.task_done()
                        continue

                    # self.wait_queue.put(task)
                    self.retry_queue.put(task)

                case ChapterResult.ERROR:
                    task.tries += 1
                    logger.warning("重试任务 {} - {} ({}/{} 次尝试)", task.course["title"], task.point["title"],
                                   task.tries,
                                   self.max_tries)
                    if task.tries >= self.max_tries:
                        logger.error("任务重试次数达到上限: {} - {}", task.course["title"], task.point["title"])
                        self.failed_tasks.append(task)
                        self.task_queue.task_done()
                        continue
                    self.retry_queue.put(task)

                case _:
                    logger.error("任务 {} 的状态无效 {}", task.result, task.point["title"])
                    self.failed_tasks.append(task)
                    self.task_queue.task_done()

    @log_error
    def retry_thread(self):
        try:
            while True:
                task = self.retry_queue.get()
                self.task_queue.put(task)
                # task_done is not called when a task failed and needs to be retried so if is reinserted into the queue,
                # the task num will increase by one and become more than the real task number
                self.task_queue.task_done()
                time.sleep(self.retry_interval)
        except ShutDown:
            pass


def process_chapter(chaoxing: Chaoxing, course: dict[str, Any], point: dict[str, Any], speed: float) -> ChapterResult:
    """处理单个章节"""
    logger.info(f'当前章节: {point["title"]}')
    if point["has_finished"]:
        logger.info(f'章节：{point["title"]} 已完成所有任务点')
        return ChapterResult.SUCCESS

    # 随机等待，避免请求过快
    chaoxing.rate_limiter.limit_rate(random_time=True, random_min=0, random_max=0.2)

    # 获取当前章节的所有任务点
    job_info = None
    jobs, job_info = chaoxing.get_job_list(course, point)

    # 发现未开放章节, 根据配置处理
    if job_info.get("notOpen", False):
        return ChapterResult.NOT_OPEN

    # 已经默认处理空任务，此处不需要判断
    if not jobs:
        pass

    job_results: list[StudyResult] = []
    for job in jobs:
        result = process_job(chaoxing, course, job, job_info, speed)
        job_results.append(result)

    for result in job_results:
        if result.is_failure():
            return ChapterResult.ERROR

    return ChapterResult.SUCCESS


def build_tasks(chaoxing: Chaoxing, course_task: list[dict]) -> list[ChapterTask]:
    """读取所选课程的全部章节, 生成任务列表."""
    tasks: list[ChapterTask] = []
    for course in course_task:
        logger.info(f"正在读取课程章节: {course['title']}")
        point_list = chaoxing.get_course_point(
            course["courseId"], course["clazzId"], course["cpi"]
        )
        for i, point in enumerate(point_list["points"]):
            tasks.append(ChapterTask(point=point, index=i, course=course))
    return tasks


def run_tasks(chaoxing: Chaoxing, tasks: list[ChapterTask], config: dict) -> JobProcessor:
    """并发执行任务点并返回处理器(含失败任务)."""
    _old_format_sizeof = tqdm.format_sizeof
    tqdm.format_sizeof = format_time
    try:
        processor = JobProcessor(chaoxing, tasks, config)
        processor.run()
    finally:
        tqdm.format_sizeof = _old_format_sizeof
    return processor


def filter_courses(all_course, course_list):
    """过滤要学习的课程"""
    if not course_list:
        # 手动输入要学习的课程ID列表
        print("*" * 10 + "课程列表" + "*" * 10)
        for course in all_course:
            print(f"ID: {course['courseId']} 班级ID: {course['clazzId']} 课程名: {course['title']}")
        print("*" * 28)
        print("提示: 同一 courseId 下若存在多个班级, 将分别完成。")
        try:
            course_list = input(
                "请输入想要学习的课程列表,以逗号分隔,例: 2151141,189191,198198\n"
            ).split(",")
        except Exception as e:
            raise InputFormatError("输入格式错误") from e

    # 筛选需要学习的课程
    course_task = []
    seen_keys = set()
    for course in all_course:
        key = (course["courseId"], course["clazzId"])
        if course["courseId"] in course_list and key not in seen_keys:
            course_task.append(course)
            seen_keys.add(key)

    # 如果没有指定课程，则学习所有课程
    if not course_task:
        course_task = all_course

    return course_task


def format_time(num, suffix='', divisor=''):
    total_time = round(num)
    sec = total_time % 60
    mins = (total_time % 3600) // 60
    hrs = total_time // 3600

    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{sec:02d}"

    return f"{mins:02d}:{sec:02d}"


def report_result(processor: JobProcessor) -> None:
    """输出执行结果摘要."""
    failed = processor.failed_tasks
    if failed:
        logger.warning(f"执行结束, 失败任务点 {len(failed)} 个:")
        for task in failed:
            logger.warning(f"  - {task.course['title']} / {task.point['title']}")
    else:
        logger.info("执行结束, 无失败任务点")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="超星学习通刷课 CLI (核心刷课 + AI 答题)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-c", "--config", type=str, default=None,
                        help="使用配置文件运行程序(跳过交互向导)")
    parser.add_argument("-u", "--username", type=str, default=None, help="手机号账号")
    parser.add_argument("-p", "--password", type=str, default=None, help="登录密码")
    parser.add_argument("-l", "--list", type=str, default=None, help="要学习的课程ID列表, 以 , 分隔")
    parser.add_argument("-s", "--speed", type=float, default=1.0, help="视频播放倍速 (默认1, 最大2)")
    parser.add_argument("-j", "--jobs", type=int, default=4, help="同时进行的章节数 (默认4)")
    parser.add_argument("--use-cookies", action="store_true", help="使用cookies登录")
    parser.add_argument("-a", "--notopen-action", type=str, default="retry",
                        choices=["retry", "ask", "continue"],
                        help="遇到关闭任务点时的行为: retry-重试, ask-询问, continue-继续")
    parser.add_argument("--retry-interval", type=float, default=1.0, help="重试等待时间, 单位秒")
    return parser.parse_args()


def build_config_from_args(args):
    """从命令行参数构建配置(无配置文件时使用默认tiku配置)"""
    common_config = default_common_config()
    common_config.update({
        "use_cookies": args.use_cookies,
        "username": args.username,
        "password": args.password,
        "course_list": [item.strip() for item in args.list.split(",") if item.strip()] if args.list else None,
        "speed": args.speed or 1.0,
        "jobs": args.jobs,
        "notopen_action": args.notopen_action or "retry",
        "retry_interval": args.retry_interval or 1.0,
    })
    # 兼容从默认 config.ini 读取题库
    _, tiku_config = load_ini(CONFIG_PATH)
    if not tiku_config:
        tiku_config = default_tiku_config()
    return common_config, tiku_config


def init_chaoxing(common_config, tiku_config, config_path=None, check_ai=None):
    """初始化超星实例.

    check_ai 为 None 时, 由配置项 [tiku] check_llm_connection 决定是否做连通性测试.
    """
    account = Account(common_config.get("username", ""), common_config.get("password", ""))
    tiku = create_tiku(tiku_config, config_path=config_path or CONFIG_PATH)

    if check_ai is None:
        raw = tiku_config.get("check_llm_connection", None)
        check_ai = True if raw is None or str(raw).strip() == "" else str_to_bool(raw)

    if check_ai and not tiku.DISABLE and str(tiku_config.get("provider", "")).strip().upper() == "AI":
        logger.info("正在验证答题AI连通性...")
        if not tiku.check_llm_connection():
            logger.error("答题AI连接检查失败")
            choice = ask("答题AI连接检查失败, 是否继续运行? (Y/n): ", default="y")
            if choice.lower() == "n":
                raise RuntimeError("用户取消运行")

    chaoxing = Chaoxing(
        account=account,
        tiku=tiku,
        query_delay=float(tiku_config.get("delay", 0) or 0),
        work_max_retries=int(common_config.get("work_max_retries", 3)),
        work_redo_enabled=bool(common_config.get("work_redo_enabled", False)),
    )
    return chaoxing


def run_non_interactive(common_config, tiku_config, course_list=None):
    """命令行/配置文件模式."""
    common_config["speed"] = min(2.0, max(1.0, float(common_config.get("speed", 1.0))))
    common_config.setdefault("notopen_action", "retry")

    chaoxing = init_chaoxing(common_config, tiku_config)

    state = chaoxing.login(login_with_cookies=bool(common_config.get("use_cookies", False)))
    if not state["status"]:
        raise LoginError(state["msg"])

    all_course = chaoxing.get_course_list()
    course_task = filter_courses(all_course, course_list if course_list is not None else common_config.get("course_list"))

    logger.info(f"课程列表过滤完毕, 当前课程任务数量: {len(course_task)}")
    tasks = build_tasks(chaoxing, course_task)
    processor = run_tasks(chaoxing, tasks, common_config)
    report_result(processor)
    logger.info("所有课程学习任务已完成")


def run_interactive():
    """默认模式: 读取 config.ini -> 登录 -> 选课 -> 刷课.

    答题AI只能通过 config.ini 的 [tiku] 段配置, 程序不提供配置向导.
    """
    print(BANNER)

    # 首次运行: 根据模板生成一份无注释的 config.ini, 让用户自行填写
    if not ensure_config(CONFIG_PATH):
        print(f"  已生成配置文件: {CONFIG_PATH}")
        print(tiku_config_hint())
        return

    common_config, tiku_config = load_ini(CONFIG_PATH)

    # 答题AI未配置完整时直接退出, 指引用户去改配置文件
    missing = missing_tiku_fields(tiku_config)
    if missing:
        logger.error("答题AI配置不完整: " + ", ".join(missing))
        print(tiku_config_hint())
        return

    tiku_config["endpoint"] = normalize_endpoint(tiku_config.get("endpoint", ""))

    base_common = default_common_config()
    base_common.update({k: v for k, v in common_config.items() if v is not None})

    # 账号
    username, password, remember = wizard_account(base_common)
    base_common["username"] = username
    base_common["password"] = password if remember else ""

    # 运行参数
    base_common = wizard_runtime(base_common)

    # 保存配置(无论是否记住密码, 都保存账号与运行参数)
    save_ini(CONFIG_PATH, base_common, tiku_config)

    # 登录(连通性测试由 init_chaoxing 按 check_llm_connection 配置决定)
    chaoxing = init_chaoxing(base_common, tiku_config)
    login_with_retry(chaoxing)

    # 课程选择
    all_course = chaoxing.get_course_list()
    course_task = select_courses(all_course)
    logger.info(f"已选择 {len(course_task)} 门课程, 开始刷课")

    tasks = build_tasks(chaoxing, course_task)
    processor = run_tasks(chaoxing, tasks, base_common)
    report_result(processor)
    logger.info("所有课程学习任务已完成")


def main():
    """主程序入口"""
    args = parse_args()

    if args.config or args.username:
        common_config, tiku_config = load_ini(args.config) if args.config else ({}, {})
        if args.username:
            cli_common, cli_tiku = build_config_from_args(args)
            common_config.update({k: v for k, v in cli_common.items() if v is not None})
            if not tiku_config:
                tiku_config = cli_tiku
        if not tiku_config:
            tiku_config = default_tiku_config()
        if not common_config:
            common_config = default_common_config()
        run_non_interactive(common_config, tiku_config, common_config.get("course_list"))
    else:
        run_interactive()


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code not in (0, None):
            logger.error(f"程序异常退出, 返回码: {e.code}")
        sys.exit(e.code)
    except KeyboardInterrupt:
        logger.error("程序被用户手动中断")
    except LoginError as e:
        logger.error(f"登录失败: {e}")
    except BaseException as e:
        logger.error(f"错误: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        raise
