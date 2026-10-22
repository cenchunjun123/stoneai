# stoneai — AI 自动化编程工具包 for CAREL STone

为卡乐（CAREL）**STone** 编程软件（c.suite 6.x / STone 1.8.x）提供的一套
**不打开 IDE、不点鼠标**的自动化编程能力：

- 通过 STone 官方自动化 API（`SToneCLI iron-python`）创建工程、注册源码、编译
- 把编译器的诊断结果解析成**结构化数据**（文件 / 行 / 列 / 错误码 / 消息）
- 提取**符号表**：POU、成员接口（输入/输出/局部变量及类型）、变量、任务
- 生成**可直接编译通过**的 ST 骨架代码（PROGRAM / FUNCTION_BLOCK / 任务配置）
- 内置 **System.* 库 API 知识库**（1000+ 条）与 IDE 代码片段
- 以 **MCP server** 形式暴露给 AI agent，实现“生成 → 编译 → 读错误 → 修复”闭环

> 纯工具层，**不绕过授权**：编译需要本机安装 STone 且持有有效许可证
> （`stoneai doctor` 会实际编译一个临时工程来验证）。

---

## 安装

需要 Windows + Python 3.10+ + 已安装的 CAREL STone（默认路径或 `STONEAI_CLI`）。

```powershell
cd C:\Users\liugu\Desktop\STone测试\stoneai
pip install -e .
stoneai doctor
```

`doctor` 输出类似：

```
SToneCLI      : C:\Program Files (x86)\CAREL\STone\SToneCLI.exe  [OK]
workroot      : C:\Users\liugu\.stoneai
System libs   : ...  [OK]
SToneAPI      : IronPython 3.4.2 [OK]
license/build : OK (dummy solution compiled)
```

---

## 十分钟上手

### 1. 建一个工程（中文路径没问题）

```powershell
stoneai new D:\我的项目 ChillerMgmt
```

### 2. 让 AI 生成一个功能块并编译

```python
from stoneai import api, stgen

sol = api.open_solution(r"D:\我的项目\ChillerMgmt\ChillerMgmt.stone")
prj = sol.project

fb = stgen.fan_block("FanCtrl1")           # 带滞回的两点控制骨架
prj.add_st_file("FanCtrl", fb.render())    # 写盘 + 注册 + 自动编译
rep = prj.build()
print(rep.summary())                       # BUILD OK
```

### 3. 出错了？拿到结构化诊断

```python
rep = prj.build()
for e in rep.errors:
    print(e.code, e.message, e.file, e.line, e.col)
```

```
E0078 The name 'bBroken' could not be found ... C:\...\FanCtrl.st 17 11
```

### 4. 读符号表，知道工程里“现在有什么”

```python
idx = prj.symbols()
idx.summary()                              # configuration=1, member=6, pou=2, ...
idx.pou_interfaces()["FanCtrl1"]
# {'inputs': ['rSetpoint','rActual'], 'outputs': ['bOut'],
#  'locals': ['rHysteresis','bEnable'],
#  'types': {'rSetpoint':'REAL', ...}}
```

### 5. 查 System 库 API

```powershell
stoneai search alarm
stoneai snippet FOR
```

---

## MCP server（给 AI agent 用）

```json
{
  "mcpServers": {
    "stoneai": { "command": "python", "args": ["-m", "stoneai.mcp_server"] }
  }
}
```

可用工具：

| 工具 | 作用 |
|---|---|
| `stone_doctor` | 环境/许可证自检（真实编译一个临时工程） |
| `stone_solution_create` | 由模板创建工程 |
| `stone_solution_state` | 列出项目 / 文件 / 配置 |
| `stone_files_add` | 写入并注册 `.st` 源码，同时编译 |
| `stone_build` | 编译，返回结构化错误 / 警告 + `flash.bin` 路径 |
| `stone_symbols` | 符号表（POU、成员接口、变量、任务），支持 `query=` 过滤 |
| `stone_api_search` | 搜索 System.* 库 API |
| `stone_snippet` | 查看 IDE 自带 ST 代码片段 |
| `stone_pou_generate` | 生成可编译的 POU 骨架 |
| `stone_target_connect` | 连接目标 (`TcpIp,10.10.9.128,4122`) |
| `stone_watch_read` | 从已连接目标读变量 |

典型 AI 闭环：`stone_api_search` 查 API → `stone_pou_generate` 出骨架 →
补上业务逻辑 → `stone_files_add` 编译 → `stone_build` 读错误 → 改 → 再编译。

---

## 工作原理（及踩过的坑）

1. **一切走 `SToneCLI.exe iron-python`**。STone 内嵌 IronPython 3.4，
   注入 `stone` 全局对象（`Solution` / `Target`），提供
   `CreateNewSolution` / `AddFile` / `Build`（返回 `IResult`）等 API。
   这是官方自动化入口，**不需要打开 IDE**。

2. **每次调用都是一个全新的 STone 进程**，`stone` 对象不跨进程保持状态。
   所以库的设计是“一次调用一个步骤序列（steps）”，在同一进程内开工程、
   操作、保存。

3. **命令行参数不能含中文**。SToneCLI 会把 argv 里的非 ASCII 字符弄成
   `????`（连工作目录里的中文也一样），例如 `C:\Users\liugu\Desktop\STone????`。
   所以所有路径只走 **JSON 负载文件**，脚本副本放在 ASCII 安全的
   `~/.stoneai` 下。工程本身放在任何中文路径里都正常。

4. **写操作必须立即 `Save`**。`AddFile` 只改内存，跨进程就会丢；
   `stoneai` 内部每次变更都在同一进程里 `save_solution`。

5. **`AddFile` 的目标参数是“文件夹”不是文件名**，传文件名会静默失败；
   新文件要先写到工程外的暂存目录再被“复制进来”。

6. **`.stone` / `.stprj` 是明文 XML**（根节点 `SToneSolution` / `SToneProject`），
   但本工具**不手写它们**——交给官方 API 生成，永远不会格式错。

7. **编译产物在 `Output/<资源>/<配置>/`**：`compilation.xml`（诊断 + 符号表，
   是权威数据源）、`varListInfo.xml`（内存分配）、`generation.xml`、
   `flash.bin`（目标固件包）。

8. **`USING System;` 需要工程引用 System 库**。新建工程默认没有引用任何库，
   生成器默认**不**输出 USING，保证开箱即编。
   `System.*` 库 API（日志、报警、BACnet、定时器…）由 `stoneai search` 提供检索，
   要在代码里调用它们，需给工程加库：`prj.add_library(r"D:\libs\X.stlib")`，
   或直接打开客户的既有设备工程（自带库与目标平台）——这是做真实项目的推荐路径。

9. **目标平台（target）与设备插件绑定**：`pCOProject` 等模板需要对应插件，
   本机只有 `BaseProject` / `EmptyProject`。`stoneai doctor` 会如实报告。

9. **IEC 各 VAR 节都由 `END_VAR` 结束**（没有 `END_VAR_INPUT`），
   这是官方库源码里的写法，也是 `stgen` 遵守的规则。

---

## 已知限制

- **新建工程默认不带任何库**：`BaseProject` 只支持纯 IEC 61131-3。
  要调用 `System.*`（日志/报警/通讯/定时器…），用
  `prj.add_library("xxx.stlib")` 加库，或**直接打开既有设备工程**
  （`stoneai state <工程.stone>`）——真实项目推荐这么做。
- **设备模板（pCOProject 等）需要插件**，插件文件由各产品线提供。

- **只处理源码与构建**：UI 编辑器（画面 `.stgui`）、协议配置（`.protocfg`）、
  翻译等不在本工具范围内。
- **下载到实体机**需要目标连接（`stoneai connect` / `stoneai watch`），
  本工具暴露了 API 但没有自动安全护栏——**下载前请人工确认现场安全**。
- **逻辑体由 AI 编写**：`stgen` 只生成保证编译通过的骨架，控制逻辑是 agent 的职责。
- 只在 Windows + STone 1.8.11 上验证过。

## License

MIT。本项目独立开发，与 CAREL Industries S.p.A. 无隶属关系。
STone、CAREL 是其各自所有者的商标。
