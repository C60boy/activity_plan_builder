# Agent 自主安装提示词

把下面整段内容，连同 `activity-plan-builder` 压缩包一起发给目标 Agent。

---

你是负责安装技能包的执行 Agent。当前环境已具备：解压能力、Python 3.10+，以及你自己的技能目录或 MCP 配置的写入权限。完成安装并验证。

## 任务

把压缩包中的 `activity-plan-builder` 安装为你可用的技能，并/或注册为 MCP 服务，最后给出验证结果。

## 步骤

1. 解压压缩包，进入 `activity-plan-builder` 目录；阅读 `SKILL.md` 了解技能工作方式（`README.md` 是面向用户的说明，无需阅读）。
2. **先询问用户安装范围，二选一，未回答前不要开始安装：**
   - **全局安装**：把技能复制到你的全局技能目录，并写入持久化的 MCP 配置；安装完成后所有会话都可以使用。
   - **仅本会话安装**：只保留解压目录，不修改任何全局技能目录或 MCP 配置文件；本会话内直接通过解压目录里的 `scripts/apb.py` 与 `mcp/server.py` 使用，会话结束后失效（解压目录可自行删除）。
   向用户提问时，用一句话说明两种方式的区别，并给出推荐（默认推荐全局安装）。
3. 检查依赖：
   - `python -c "import docx; print(docx.__version__)"`
   - 失败则执行 `python -m pip install "python-docx>=1.1,<2"`；
   - 仍失败则加 `--user`，或使用清华镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。
4. 如果用户选择**全局安装**，且你支持 Agent Skills（即支持 `SKILL.md`）：
   - 把整个 `activity-plan-builder` 文件夹复制到你的技能目录；
   - 确保最终存在 `<技能目录>/activity-plan-builder/SKILL.md`；
   - 记录该路径为 `SKILL_DIR`。
   如果用户选择**仅本会话安装**：跳过复制，`SKILL_DIR` 直接指向解压目录。
5. 如果支持 MCP：
   - 全局安装：先备份你现有的 MCP 配置文件，再合并下面这段 `mcpServers` 配置，**不要删除或覆盖其他 server**；
   - 仅本会话安装：不要修改任何配置文件，把下面配置中的路径替换后仅在本会话内使用（例如临时启动 stdio 服务或按你平台的方式临时注册），并在报告里注明“会话结束后失效”。

```json
{
  "mcpServers": {
    "activity-plan-builder": {
      "command": "<Python 解释器绝对路径>",
      "args": ["<SKILL_DIR>/mcp/server.py"],
      "env": { "PYTHONUTF8": "1" }
    }
  }
}
```

   - `command` 必须使用 `python -c "import sys; print(sys.executable)"` 得到的绝对路径；
   - `args` 指向 `SKILL_DIR` 下的 `mcp/server.py`。

6. 验证，以下三项全部通过才算完成：
   - `python "<SKILL_DIR>/scripts/apb.py" list modules`：输出 26 个模块；
   - 对 `<SKILL_DIR>/mcp/server.py` 发送 MCP `initialize` 与 `tools/list`：返回 10 个工具；
   - `python "<SKILL_DIR>/scripts/apb.py" build "<SKILL_DIR>/examples/demo.plan.json" -o "<临时目录>/demo.docx"`：生成 DOCX，且文件大于 30 KB。
7. 如果验证失败，最多自动修复两次（依赖、路径、权限）；仍失败则停止，并报告具体错误和已尝试的命令。
8. 最后输出：
   - 安装范围（全局 / 仅本会话）
   - 安装方式（技能 / MCP / 两者）
   - `SKILL_DIR` 与 MCP 配置文件（如有）的绝对路径
   - 三项验证结果
   - 一句话使用示例

## 约束

- 命令中的 `python` 请替换为你环境里实际可用的解释器（`python` / `python3` / `py -3`）。
- 不要修改与本技能无关的配置项。
- 修改任何已有配置前先备份。
- 不要编造验证结果；命令失败就如实报告。
- 不要删除压缩包或原始解压目录。
