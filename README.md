# :computer: 超星学习通刷课 CLI（核心刷课 + AI 答题）

<p align="center">
  <a href="https://github.com/userchengyang/-"><img src="https://img.shields.io/github/license/userchengyang/-" alt="License"></a>
  <img src="https://img.shields.io/badge/Python-3.13%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/version-3.1.3-green" alt="Version">
</p>

超星学习通（超星尔雅 / 泛雅）命令行自动化工具：无人值守完成视频、文档、阅读、章节检测、直播等任务点，章节检测由 **OpenAI 兼容接口的 AI** 自动作答。

> 本项目衍生自 [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing)，感谢原作者与贡献者。

## :sparkles: 与上游的差异

- **纯配置文件驱动**：答题 AI 的接口地址 / Key / 模型只能写在 `config.ini` 的 `[tiku]` 段，程序不提供任何交互式配置向导
- **AI 答题**：题库模块收敛为单一 `AI` provider（OpenAI 兼容接口），支持连通性测试
- **并发刷课**：按章节并发执行任务点，`jobs` 可调
- **一键启动**：Windows 下双击 `启动.bat`，自动识别本机 Python 并补装依赖
- **移除部分上游功能**：第三方题库、外部通知、章节学习次数等未包含在本版本中

## :point_up: 功能

| 任务类型 | 说明 |
| --- | --- |
| 视频 / 音频 | 倍速播放（最大 2 倍），进度上报，异常任务自动跳过 |
| 文档 | 自动标记已读 |
| 阅读 | 自动完成阅读任务点 |
| 章节检测 | AI 作答 + 覆盖率判定 + 提交 / 保存，支持答错重做 |
| 直播 | 独立线程处理直播任务点 |
| 登录 | 首次登录后账号绑定本机，之后自动沿用登录态，账号不可更换 |
| 关闭任务点 | `retry` / `ask` / `continue` 三种策略 |

## :books: 使用方法

### 环境要求

- Python **3.13+**（Windows / macOS / Linux），且 `python` 已加入 PATH
- 一个 OpenAI 兼容接口（DeepSeek、Kimi、通义、OpenAI 等均可）

> 本程序**不内置** Python 运行环境。目标电脑必须先装好 Python，否则无法启动。

### 一键启动（Windows）

1. 双击 `启动.bat`
2. 首次运行会在同目录生成 `config.ini`，程序随即退出并提示你补全 `[tiku]` 段
3. 编辑 `config.ini`，填好 `endpoint` / `key` / `model`
4. 再次双击 `启动.bat`，输入手机号与密码；登录成功后账号即绑定本机
5. 之后每次双击都是自动登录，直接进选课界面

> `启动.bat` 会检测本机 Python，缺少依赖时自动 `pip install -r requirements.txt`。
> 本机没有 Python 时会直接报错退出。

### 源码运行

```bash
git clone https://github.com/userchengyang/-.git
cd <仓库目录>

pip install -r requirements.txt
python main.py            # 读取 config.ini, 自动登录已绑定账号(首次会要求输入)
```

### 配置文件运行

`config_template.ini` 是**带注释的字段说明手册**，把它复制为 `config.ini` 并填写：

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
| `-c, --config` | 指定配置文件路径 |
| `-u / -p` | 手机号 / 密码（账号必须与已绑定账号一致；`-p` 传新密码会同步更新本地） |
| `-l, --list` | 课程 ID 列表，逗号分隔（留空学习全部） |
| `-s, --speed` | 视频倍速，默认 1，最大 2 |
| `-j, --jobs` | 并发章节数，默认 4 |
| `--use-cookies` | 已废弃，登录态现在自动沿用 |
| `--change-password` | 只更新已绑定账号的密码，账号不变 |
| `-a, --notopen-action` | 关闭任务点策略：`retry` / `ask` / `continue` |
| `--retry-interval` | 重试等待秒数，默认 1.0 |

### 账号绑定（一机一号）

首次登录成功后，程序会生成 `account.json`，把账号锁死在这台机器上：

- **之后每次启动自动沿用登录态**，不用再输密码；登录态过期时用本地保存的密码静默重登
- **账号不可更换**：交互界面不给换号入口，命令行 `-u` 传别的号会直接拒绝
- **在手机 / 网页上改了密码** → 本地那份失效 → 启动时提示输入新密码（账号不变），
  也可以随时单独跑一次 `启动.bat --change-password`
- **一机一号**：`account.json` 记了本机机器码，整个文件夹拷到别的电脑会判定无效。
  需要在某台机器上重新绑定，删掉 `account.json` 再运行一次即可

> 这层做的是抬高随手换号的成本，不是安全边界：密码用内置密钥做 AES，只防明文出现在文件里，
> 挡不住逆向。账号密码不再写进 `config.ini`。
>
> 注意：程序会校验登录态属于哪个账号。如果 `cookies.txt` 里残留的是别的号的 cookie，
> 会被丢弃并改用保存的密码重新登录 —— 不会拿错号的登录态去刷课。

### Docker 运行

```bash
docker build -t chaoxing .
docker run -it -v /本地路径/config.ini:/config/config.ini chaoxing
```

镜像启动时会把 `config_template.ini` 复制为 `/config/config.ini` 作为默认配置。

## :wrench: 答题 AI 配置

答题 AI **只能**通过配置文件 `config.ini` 的 `[tiku]` 段配置（`provider` 固定为 `AI`），程序不再提供任何交互式配置向导。
`endpoint`、`key`、`model` 三项缺任意一项，程序启动时会直接退出并提示。

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
├── main.py              # 入口：读 config.ini → 自动登录绑定账号 → 选课 → 刷课
├── 启动.bat              # Windows 一键启动（检测本机 Python 并补装依赖）
├── 制作便携版.bat / 打包便携版.bat  # 构建可脱离 Python 独立运行的便携版
├── config_template.ini  # 带注释的字段说明手册
├── account.json         # 运行期生成：账号绑定（含机器码，删掉即解绑）
├── cookies.txt          # 运行期生成：登录态
├── Dockerfile
├── api/
│   ├── base.py          # Chaoxing 核心类：登录、课程、各类任务点
│   ├── answer.py        # 答题模块（AI / OpenAI 兼容接口）与答案缓存
│   ├── answer_check.py  # 答案检查与验证
│   ├── binding.py       # 账号绑定：一机一号、锁死账号、只允许改密码
│   ├── device.py        # 机器指纹
│   ├── cipher.py        # AES 加解密（登录参数 + 本地保存的密码）
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
