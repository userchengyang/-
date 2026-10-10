# :computer: 超星学习通刷课 CLI（核心刷课 + AI 答题）

<p align="center">
  <a href="https://github.com/userchengyang/-"><img src="https://img.shields.io/github/license/userchengyang/-" alt="License"></a>
  <img src="https://img.shields.io/badge/Python-3.13%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/version-3.1.3-green" alt="Version">
</p>

超星学习通（超星尔雅 / 泛雅）命令行自动化工具：无人值守完成视频、文档、阅读、章节检测、直播等任务点，章节检测由 **OpenAI 兼容接口的 AI** 自动作答。

> 本项目衍生自 [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing)，感谢原作者与贡献者。

## :sparkles: 与上游的差异

- **交互向导**：首次运行可视化配置答题 AI、账号与运行参数，自动生成 `config.ini`，无需手动改文件
- **AI 答题**：题库模块收敛为单一 `AI` provider（OpenAI 兼容接口），支持连通性测试与模型列表拉取
- **并发刷课**：按章节并发执行任务点，`jobs` 可调
- **一键启动**：Windows 下双击 `启动.bat`，自动补装依赖
- **移除部分上游功能**：第三方题库、外部通知、章节学习次数等未包含在本版本中

## :point_up: 功能

| 任务类型 | 说明 |
| --- | --- |
| 视频 / 音频 | 倍速播放（最大 2 倍），进度上报，异常任务自动跳过 |
| 文档 | 自动标记已读 |
| 阅读 | 自动完成阅读任务点 |
| 章节检测 | AI 作答 + 覆盖率判定 + 提交 / 保存，支持答错重做 |
| 直播 | 独立线程处理直播任务点 |
| 登录 | 账号密码 / Cookie 两种方式，登录失败自动重试 |
| 关闭任务点 | `retry` / `ask` / `continue` 三种策略 |

## :books: 使用方法

### 环境要求

- Python **3.13+**（Windows / macOS / Linux）
- 一个 OpenAI 兼容接口（DeepSeek、Kimi、通义、OpenAI 等均可）

### 一键启动（Windows）

双击 `启动.bat`，按提示完成首次配置即可。

### 源码运行

```bash
git clone https://github.com/userchengyang/-.git
cd <仓库目录>

pip install -r requirements.txt
python main.py            # 交互向导模式（推荐）
```

### 配置文件运行

复制 `config_template.ini` 为 `config.ini`，填写账号与 AI 配置：

```bash
python main.py -c config.ini
```

### 命令行运行

```bash
python main.py -u 手机号 -p 密码 \
  -l 课程ID1,课程ID2 \
  -s 1.5 -j 4 -a retry
```

| 参数 | 说明 |
| --- | --- |
| `-c, --config` | 指定配置文件，跳过交互向导 |
| `-u / -p` | 手机号 / 密码 |
| `-l, --list` | 课程 ID 列表，逗号分隔（留空学习全部） |
| `-s, --speed` | 视频倍速，默认 1，最大 2 |
| `-j, --jobs` | 并发章节数，默认 4 |
| `--use-cookies` | 使用 `cookies.txt` 登录 |
| `-a, --notopen-action` | 关闭任务点策略：`retry` / `ask` / `continue` |
| `--retry-interval` | 重试等待秒数，默认 1.0 |

### Docker 运行

```bash
docker build -t chaoxing .
docker run -it -v /本地路径/config.ini:/config/config.ini chaoxing
```

镜像启动时会把 `config_template.ini` 复制为 `/config/config.ini` 作为默认配置。

## :wrench: 答题 AI 配置

配置文件 `[tiku]` 段（`provider` 固定为 `AI`）：

```ini
[tiku]
provider = AI
check_llm_connection = true   ; 启动时做一次连通性测试
submit = true                 ; true=达到覆盖率即提交, false=只保存不提交
cover_rate = 0.8              ; 最低答案覆盖率(0~1)
delay = 1.0                   ; 连续查题间隔(秒)
endpoint = https://api.deepseek.com/v1
key = sk-xxxx
model = deepseek-chat
min_interval_seconds = 1
http_proxy =                  ; 可选, 例如 http://127.0.0.1:7890
```

- `submit = true`：答完题并达到 `cover_rate` 才提交，**正确率不做保证**
- `submit = false`：只保存搜到的答案，可自行前往学习通检查后提交
- 不配置 AI 时，章节检测等需答题的任务会自动跳过
- 对任务点需解锁的课程，必须配置 AI 才能推进

## :page_facing_up: 项目结构

```
├── main.py              # 入口：交互向导 / 命令行 / 配置文件三种模式
├── 启动.bat              # Windows 一键启动
├── config_template.ini  # 配置模板
├── Dockerfile
├── api/
│   ├── base.py          # Chaoxing 核心类：登录、课程、各类任务点
│   ├── answer.py        # 答题模块（AI / OpenAI 兼容接口）与答案缓存
│   ├── answer_check.py  # 答案检查与验证
│   ├── cipher.py        # AES 加解密
│   ├── cookies.py       # Cookie 管理
│   ├── cxsecret_font.py / font_decoder.py / decode.py  # 超星字体与页面解析
│   ├── live.py / live_process.py                       # 直播任务
│   ├── captcha.py       # 验证码识别（ddddocr，未启用）
│   ├── logger.py        # 日志
│   └── exceptions.py    # 自定义异常
└── resource/
    └── font_map_table.json  # 字体映射表
```

## :warning: 免责声明

- 本代码遵循 [GPL-3.0 License](LICENSE) 协议，允许**开源 / 免费使用、引用、修改及衍生代码的开源 / 免费使用**；**不允许**将修改或衍生代码作为闭源商业软件发布销售，**禁止**使用本代码盈利；以此代码为基础的程序**必须**同样遵循 GPL-3.0 协议
- 本代码仅用于**学习与技术讨论**，禁止用于盈利
- 使用本代码违反学校规章制度或平台服务协议所产生的一切后果（包括但不限于账号封禁、成绩作废、纪律处分）由使用者自行承担，与本项目作者无关
