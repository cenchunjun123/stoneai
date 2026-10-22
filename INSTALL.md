# 团队安装指南

给同事的一页纸。**三步装完，10 分钟内能让 AI 直接写 STone 程序。**

---

## 前置条件

| 条件 | 检查方法 |
|---|---|
| Windows 10/11 | — |
| Python 3.10+ | `python --version` |
| CAREL STone 已安装 | 默认 `C:\Program Files (x86)\CAREL\STone\` |
| STone 许可证有效 | 装完跑 `stoneai doctor` 会验证 |

> STone 没装在默认路径时，用 `--cli` 参数指定：
> `stoneai --cli "D:\STone\SToneCLI.exe" doctor`

---

## 第一步：安装 stoneai

### 方式 A：从 Git 仓库（推荐）

```powershell
pip install git+https://<你的仓库地址>/stoneai.git
```

### 方式 B：clone 后本地安装

```powershell
git clone <你的仓库地址>/stoneai.git
cd stoneai
pip install .
```

### 方式 C：从共享盘拿 wheel

```powershell
pip install "\\共享盘路径\stoneai-0.1.0-py3-none-any.whl"
```

**验证：**

```powershell
stoneai doctor
```

全部 `[OK]` 且最后一行 `license/build : OK` 就是装好了。

> `stoneai` 命令找不到时，用 `python -m stoneai` 代替（效果完全一样）。

---

## 第二步：装 AI 技能（Skill）

让 AI 知道 STone 的正确用法和所有坑。

```powershell
stoneai install-skill
```

它会自动找你的 skills 目录（`~/.agents/skills`、`~/.claude/skills`、
`~/.dsh/skills` 中第一个存在的），把 `my-stoneai-skill` 放进去。

**指定目录：**

```powershell
stoneai install-skill --target "$env:USERPROFILE\.agents\skills"
```

装完**重启 AI 客户端**（或重载 skills）才会生效。

---

## 第三步：配 MCP Server

让 AI 拥有直接操作 STone 的 11 个工具。

```powershell
stoneai mcp-config
```

会输出一段 JSON，例如：

```json
{
  "mcpServers": {
    "stoneai": {
      "command": "C:\\Python314\\python.exe",
      "args": ["-m", "stoneai.mcp_server"]
    }
  }
}
```

**把这段合并进你的 MCP 客户端配置**：

| 客户端 | 配置文件 |
|---|---|
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` |
| Claude Code | `~/.claude.json` 或项目 `.mcp.json` |
| DSH | 由界面管理 MCP server |
| Cursor | `~/.cursor/mcp.json` |

> `command` 用的是你当前 Python 的绝对路径，这样最稳。

---

## 验证装好了

在 AI 里说：

> 帮我查一下 STone 的报警日志 API 怎么用

AI 应该调用 `stone_api_search`，返回 `System.Alarm.*` 的真实函数签名。

再试：

> 建一个 STone 工程，写一个带滞回的风机控制功能块，编译通过

AI 应该走完整闭环：建工程 → 生成代码 → 编译 → 报出错误 → 修复 → 编译通过。

---

## 常见问题

**Q: `stoneai` 命令找不到**
用 `python -m stoneai` 代替。或把 Python Scripts 目录加进 PATH：
```
%APPDATA%\Python\Python3XX\Scripts
```

**Q: doctor 报 `SToneCLI MISSING`**
STone 没装或不在默认路径。用 `--cli` 指定：
```powershell
stoneai --cli "D:\你的路径\SToneCLI.exe" doctor
```

**Q: doctor 报 `license/build : FAILED`**
STone 许可证无效或过期。打开 STone IDE 确认许可证状态。
**不要试图绕过许可证** —— 这是硬门槛。

**Q: 技能装上了但 AI 不用**
1. 确认重启了客户端
2. 确认目录里确实有 `my-stoneai-skill/SKILL.md`
3. 主动说「用 my-stoneai-skill 帮我...」

**Q: MCP 工具调不出来**
1. `python -m stoneai.mcp_server` 手动跑一下，看是否报错
2. 检查配置里的 `command` 路径是否真实存在
3. 客户端里看 MCP server 状态是否 connected

**Q: 中文路径能用吗**
能。工具内部所有路径走 JSON 负载传递，不受命令行编码影响。
```

---

## 装完能做什么

- 不打开 STone IDE，直接用 AI 建工程、写程序、编译
- 编译错误自动定位到 `文件:行:列`，AI 自己改
- 自动读符号表，知道工程里有哪些 POU、变量、接口类型
- 检索 640 条 System.* 库 API 真实签名
- 生成保证编译通过的 ST 代码骨架
