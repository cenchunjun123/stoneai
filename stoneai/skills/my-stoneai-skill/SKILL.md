---
name: my-stoneai-skill
description: 卡乐 CAREL STone（c.suite 6.x）编程软件 AI 自动化编程规范与工具链，覆盖 SToneCLI iron-python 自动化 API、.st 源码生成、编译诊断闭环、符号表提取、System 库 API 检索与 MCP 接入。当需要创建/修改 STone 工程、编写或调试 IEC 61131-3 ST 程序、批量生成 POU、读取编译错误并自动修复、查询 System.* 库函数、或让 AI 直接驱动 STone 做无界面编程时使用。
---

# STone AI 自动化编程规范

来源：基于 CAREL STone 1.8.11（c.suite 6.x）真实自动化 API 探索与验证，
工具包 `stoneai` 已通过 23 项集成测试 + MCP 端到端测试全部通过。
本 skill 记录**怎么做对**、**哪些坑必须避开**。

## 一句话原则

**所有 STone 操作走官方 `SToneCLI.exe iron-python` 自动化 API，绝不手写
`.stone` / `.stprj` 工程文件，绝不用 UI 点鼠标。编译器接受是唯一的验收标准。**

---

## 一、必须遵守的 8 条铁律

1. **不手写工程文件**。`.stone`/`.stprj` 是 XML，但格式脆弱（手写报
   `Value cannot be null. (Parameter 'g')`）。用 `CreateNewSolution` 生成。

2. **每次写操作必须在同一进程内 `Save`**。STone API **跨进程无状态**，
   每次 `SToneCLI iron-python` 都是全新进程，`AddFile` 只改内存，
   不保存就丢。→ 相关步骤必须在一个 `runner.run([...])` 批次里。

3. **命令行参数绝对不能含中文**。SToneCLI 会把 argv 非 ASCII 变成 `????`
   （连工作目录里的中文也变，如 `STone测试` → `STone????`），且**真实导致
   编译失败**。→ 所有路径只走 **JSON 负载文件**，脚本副本放 ASCII 安全的
   `~/.stoneai` 下。工程本身放中文路径没问题（走负载即可）。

4. **`AddFile(source, 目的路径)` 的第二个参数是「文件夹」不是文件名**。
   传文件名会**静默失败**（返回 added:false，不报错）。
   → 新文件先写到工程**外的暂存目录**，再让 AddFile 复制进来。

5. **新建工程默认不引用任何库**（`GetLibsNames()` → `[]`）。
   → 生成器默认**不输出** `USING System;`，否则报
   `E0078 The name 'System' could not be found`。
   要调 `System.*` 必须 `prj.add_library("xxx.stlib")` 加库，或直接打开
   客户既有设备工程（推荐的真实项目路径）。

6. **所有 `VAR*` 节都用 `END_VAR` 结束**，没有 `END_VAR_INPUT` /
   `END_VAR_OUTPUT`。写错报 `E0003 Syntax error, unexpected VAR_OUTPUT`。
   这是官方库源码的写法。

7. **主 POU 名绑定在 `Properties\Resources.st`**：
   `PROGRAM MainInstance WITH MainTask : Main`。
   把 `Main` 改名但不同步改 `Resources.st` → 报
   `E0078 'Main' could not be found`。改主程序名时两处一起改。

8. **声称完成前必须 `build()` 通过**。不要凭「看起来对」交付。
   编译成功还要确认 `flash.bin` 产物存在。

---

## 二、核心 API 速查

```python
from stoneai import api, stgen, knowledge
```

### 建工程 / 开工程

```python
# 新建（中文路径完全支持）
sol = api.create_solution(r"D:\项目", "ChillerMgmt", template="BaseProject")
prj = sol.project
print(prj.path, prj.files, prj.output_dir)

# 打开既有工程（真实项目推荐走这条）
sol = api.open_solution(r"D:\客户项目\xxx.stone")
prj = sol.project_named("PLC_1") or sol.project
```

### 写代码 + 编译

```python
from stoneai import stgen

fb = stgen.Pou(
    name="ValveCtrl", kind="FUNCTION_BLOCK",
    comment="两位阀控制",
    variables=[
        stgen.Variable("rSetpoint", "REAL", input=True,  comment="设定值"),
        stgen.Variable("rActual",   "REAL", input=True,  comment="测量值"),
        stgen.Variable("bCmd",      "BOOL", output=True, comment="阀门指令"),
        stgen.Variable("rHyst",     "REAL", init="0.5",  comment="滞回"),
    ],
    body="IF rActual < rSetpoint - rHyst THEN\n    bCmd := TRUE;\n"
         "ELSIF rActual > rSetpoint THEN\n    bCmd := FALSE;\nEND_IF;",
)
prj.add_st_file("ValveCtrl", fb.render())   # 写盘 + 注册 + 自动保存
rep = prj.build()                            # → BuildReport
print(rep.summary())
```

`stgen.py` 还提供 `fan_block(name)`（带滞回的两点控制骨架）、
`Resource(configuration, resource, tasks, programs)`（生成任务配置）。

### 读诊断（关键：结构化，可直接自动修复）

```python
for e in rep.errors:
    print(e.code, e.message, e.file, e.line, e.col)
# E0078 The name 'bBroken' could not be found ... D:\...\FanCtrl.st 17 11
```

`Diagnostic` 字段：`code / level / message / file / line / col / end_line / end_col`，
`file` 是**绝对路径**。数据源是 `Output/<资源>/<配置>/compilation.xml`。

### 读符号表（写调用点前必须先查）

```python
idx = prj.symbols()
idx.summary()                            # configuration=1, member=6, pou=2, ...
idx.pous()                               # ['FanCtrl1', 'Main']
idx.members("Main")                      # [fan1]
idx.pou_interfaces()["FanCtrl1"]
# {'kind': 'FunctionBlockType',
#  'inputs':  ['rSetpoint', 'rActual'],
#  'outputs': ['bOut'],
#  'locals':  ['rHysteresis', 'bEnable'],
#  'types':   {'rSetpoint': 'REAL', 'rActual': 'REAL', ...}}
idx.search("fan")                        # 模糊查
```

### 查 System 库 API

```python
kb = knowledge.build_knowledge()          # 640 条，来自真实库源码
kb.search("alarm", limit=5)               # → [ApiEntry(kind, name, signature, doc)]
kb.topic("log")                           # 按主题
kb.snippets["FOR"]                        # IDE 自带 41 个代码片段
```

签名是从 `Data\Libraries\System\*.st` **真实解析**出来的，含形参表，例如
`FUNCTION AlarmLogManagement (VAR_IN_OUT alarm_log : ARRAY) (VAR_INPUT alarmNumber : UDINT; alarmSize : UDINT)`。
照抄拼写，不要自己猜。

---

## 三、标准工作流

### 场景 A：写一个新功能块并编译通过

1. `kb.search("<相关API>")` —— 先确认要用的库函数真实签名
2. `idx.pou_interfaces()` —— 确认要调用的既有 POU 接口
3. `stgen.Pou(...)` 生成骨架 → 填业务逻辑
4. `prj.add_st_file(name, code)` → `rep = prj.build()`
5. 若有 error：按 `file:line:col` 定位改源码 → 重新 `add_st_file` → 再 build
6. build OK 且 `rep.artifact`（flash.bin）存在 → 完成

**循环直到通过，不要中途声称完成。**

### 场景 B：接手既有工程

1. `stoneai doctor` 确认环境与许可证
2. `stoneai state <工程.stone>` 看项目 / 文件 / 配置
3. `stoneai symbol <工程.stone>` 摸清现有符号与接口
4. 改代码走场景 A

### 场景 C：编译失败排查

直接读 `rep.errors`，按错误码分派：

| 错误码 | 含义 | 处理 |
|---|---|---|
| `E0003` | 语法错误（意外 token） | 看 line/col 附近；常见是 `END_VAR_INPUT` 之类 |
| `E0078` | 名字找不到 | 缺 `USING`/缺库引用/拼错/主 POU 改名未同步 Resources.st |
| `E0085` | 命名空间重复定义 | 同名 POU 声明了两次（常见：新文件里又写了 `PROGRAM Main`） |
| `E0027` | 歧义 / 找不到匹配 | 同名实体冲突，或模板不匹配 |
| `W0016` | 变量声明未使用 | 警告，可忽略但最好清掉 |

`Position` 拼接格式是 `file(startline,startcol,endline,endcol)`。

### 场景 D：连目标机

```bash
stoneai connect <工程.stone> "TcpIp,10.10.9.128,4122"
stoneai watch   <工程.stone> <变量名>
```

**下载会改变现场控制器行为**，执行前必须确认机器旁无人。
本工具暴露了 API 但**没有做安全护栏**，下载需人工确认。

---

## 四、ST 语法要点（实测）

```iecst
{干净的 IEC 61131-3，无需 USING}
FUNCTION_BLOCK ValveCtrl
    VAR_INPUT
        rSetpoint : REAL;
        rActual   : REAL;
    END_VAR          (* 注意：不是 END_VAR_INPUT *)
    VAR_OUTPUT
        bCmd      : BOOL;
    END_VAR
    VAR
        bEnable   : BOOL := TRUE;
        arrVal    : ARRAY[0..9] OF INT;
    END_VAR

    IF bEnable AND rActual < rSetpoint THEN
        bCmd := TRUE;
    ELSE
        bCmd := FALSE;
    END_IF;
END_FUNCTION_BLOCK
```

- 变量段顺序：`VAR_INPUT` → `VAR_OUTPUT` → `VAR_IN_OUT` → `VAR_TEMP`
  → `VAR` → `VAR CONSTANT` → `VAR RETAIN`
- 枚举引用带命名空间：`LogLevel#Error_Level`
- 指针用 `^`：`log.Config^.Kind`
- 注释：`(* ... *)` 或 `//`

---

## 五、工程文件结构（读得懂就行，别手写）

```
X.stone                     ← 解决方案根（<SToneSolution>）
X\X.stprj                   ← 项目（<SToneProject>）
X\X.st                      ← 默认主程序（PROGRAM Main）
X\Properties\Resources.st   ← 任务绑定（PROGRAM MainInstance WITH MainTask : Main）
X\Output\<资源>\<配置>\      ← 编译产物
    compilation.xml         ← ★ 权威数据源：诊断 + 完整符号表
    varListInfo.xml         ← 内存分配
    generation.xml          ← POU 生成信息
    flash.bin               ← 编译成功才有的目标固件包
```

---

## 六、MCP 接入（让 AI 直接驱动 STone）

```json
{
  "mcpServers": {
    "stoneai": { "command": "python", "args": ["-m", "stoneai.mcp_server"] }
  }
}
```

11 个工具：

| 工具 | 用途 |
|---|---|
| `stone_doctor` | 环境/许可证自检（真实编译临时工程） |
| `stone_solution_create` | 由模板创建工程 |
| `stone_solution_state` | 项目 / 文件 / 配置 |
| `stone_files_add` | 写入注册 `.st` 源码并编译 |
| `stone_build` | 编译，返回结构化诊断 + flash.bin 路径 |
| `stone_symbols` | 符号表（支持 `query=` / `interfaces=true`） |
| `stone_api_search` | 搜 System.* 库 API |
| `stone_snippet` | IDE 代码片段 |
| `stone_pou_generate` | 生成可编译 POU 骨架 |
| `stone_target_connect` | 连接目标 |
| `stone_watch_read` | 读目标变量 |

典型闭环：`stone_api_search` → `stone_pou_generate` → 补逻辑 →
`stone_files_add` → `stone_build` 读错误 → 改 → 再编译。

---

## 七、命令行速查

```bash
stoneai doctor                       # 环境 + 许可证（真实编译验证）
stoneai new    <目录> <名称> [-t BaseProject]
stoneai state  <工程.stone>
stoneai add    <工程.stone> <文件.st>
stoneai build  <工程.stone> [-p 项目] [--json]
stoneai symbol <工程.stone> [--kind pou|member|variable|task] [--json]
stoneai search <关键词>
stoneai snippet [名称]
stoneai connect <工程.stone> "TcpIp,IP,PORT"
stoneai watch  <工程.stone> <变量>
```

`stoneai` 不在 PATH 时用 `python -m stoneai`。

---

## 八、已知限制（别硬碰）

- **新建工程不带任何库**：`BaseProject` 只支持纯 IEC 61131-3。
  调 `System.*` 需加库或打开既有设备工程。
- **设备模板（pCOProject 等）需要插件**，插件文件由各产品线提供，
  本机可能没有；`stoneai doctor` 会如实报告。
- **只管源码与构建**：UI 画面（`.stgui`）、协议配置（`.protocfg`）、
  翻译不在范围内。
- **许可证是硬门槛**：编译需要有效 STone 许可证，不要试图绕过。
