# SWEDeepDiver

SWEDeepDiver 是一个面向 **软件工程（SWE）问题** 的自动化分析 Agent，  
用于在真实工程环境中，对 **Android / iOS / Backend / Frontend** 等多技术栈的问题进行深度诊断与根因定位。

它模拟有经验的工程师排查习惯：从整体到局部、从现象到本质，综合利用日志、异常 Trace、多种问题文件、源码和知识库，构建“时间线 + 证据链”，最终给出结构化、可验证的诊断结论。

更多内容可查看：[掘金Blog](https://juejin.cn/post/7585600621521928232)

---

## 安装
### 使用`uv`安装（推荐）
#### 1. 安装`uv`
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
#### 2. Clone仓库
```bash
git clone https://github.com/SteveYang92/SWEDeepDiver.git SWEDeepDiver
cd SWEDeepDiver
```
#### 3. 创建虚拟环境并激活
```bash
uv venv --python 3.11
source .venv/bin/activate  # On Unix/macOS
# Or on Windows:
# .venv\Scripts\activate
```
#### 4. 安装依赖
```bash
uv pip install -r requirements.txt
```
#### 5. 安装ripgrep
```bash
brew install ripgrep # On macOS
# 其他平台安装可参考ripgrep github介绍
```
#### 6. 安装Claude Code（可选）
```bash
npm install -g @anthropic-ai/claude-code
# 更多安装方式可参考claude-code github介绍
```
> 目前AnalyzeCode工具是通过`Calude Code CLI`非交互调用实现的，如需使用代码分析功能，需有Claude Code环境

---

## 配置
### 1 Agent配置

1. 复制Agent配置模板：

```bash
cp config/config_example.toml config/config.toml
```

2. 编辑 `config/config.toml`，配置：

- DeepDiver / Inspector / Reviewer 使用的模型、地址、API Key
- 最大步数、token 限制、temperature、超时等
- 工具相关参数（如 grep 行数限制、issue 目录等）


### 2 知识配置
1. 复制知识索引配置模板：

```bash
cp config/knowledge_config_example.toml config/knowledge_config.toml
```
2. 配置知识索引：
- `config/knowledge_config.toml`：为不同知识 Key 配置关键词，Agent运行时，此信息会自动注入到上下文，Agent会据此加载问题相关的知识库
3. 配置知识库：
- 在`knowledge/`目录下创建知识文档，文档命名需和知识Key一致。
- **知识文档提供了领域特定知识，良好的文档将大大提升Agent的问题定位能力**

### 3 数据预处理配置
1. 实现接口：

```python
# 示例：自定义脱敏
from preprocess.datamask import IDataMasker

class MyDataMasker(IDataMasker):
    def mask(self, raw: str) -> str:
        # TODO: 在这里实现对敏感信息的脱敏逻辑
        return masked
```

```python
# 示例：自定义解密
from preprocess.descyptor import IDecryptor

class MyDecryptor(IDecryptor):
    def decrypt(self, input_file_path, output_dir, filename):
        # TODO: 在这里实现解密逻辑
        return output_file_path
```

2. 在 `app/processor.py` 中绑定你的实现，使之成为当前使用的策略。

Agent 在对日志进行分析前，会先通过 `process_file` 工具调用这条管线生成“处理后日志”，再进行 `grep` / `inspect` 等操作。

---

## 快速运行

可以通过 `test_case.py` 选择要演示的问题，例如：

```python
# test_case.py 示例节选
issue_backend_node_crash = r"""
Node 挂了，请分析原因
问题目录：examples/backend/node_crash
"""

# 测试入口
test_case_entry = issue_backend_node_crash
```

然后在项目根目录执行：

```bash
# 使用默认模型作为DeepDiver Agent模型
python run.py

# 或：使用 glm 模型作为DeepDiver Agent模型（需在 config.toml 中配置好对应模型）
python run.py glm
```

运行后，SWEDeepDiver 将会：

1. 读取 `test_case_entry` 中的问题描述与问题目录；
2. 自动识别问题类型与可用证据源（日志 / Trace / 代码等）；
3. 调用工具（例如 Glob → ProcessFile → Grep / Inspect 等）进行分析；
4. 构建时间线和证据链，并通过 Reviewer 审核；
5. 在终端输出结构化的诊断报告（包含结论、置信度、关键依据与时间线）。

输出示例：
```markdown
**结论**：ANR的根本原因是`HeavyService.performHeavyOperation`方法在主线程中调用了`Thread.sleep`，导致主线程阻塞超过系统允许的服务执行时间（约5秒），从而触发ANR。

**置信度**：高

**证据强度**：高

**核心依据**：

1. **日志 / Trace 证据**：
   - `03:34:05.428` MainActivity记录“Performing heavy database operation”，暗示耗时操作开始。
     - 原始内容：`12-12 03:34:05.428 16953-12345/com.example.testapp I/MainActivity: Performing heavy database operation`
   - `03:34:11.428` ActivityManager报告ANR，直接指出原因为执行服务`com.example.testapp/.HeavyService`。
     - 原始内容：`12-12 03:34:11.428 16953-12345/com.example.testapp E/ActivityManager: ANR in com.example.testapp`
     - 原始内容：`12-12 03:34:11.428 16953-12345/com.example.testapp E/ActivityManager: Reason: executing service com.example.testapp/.HeavyService`
   - **ANR Trace 显示主线程堆栈**：
     - 主线程（`"main"`）状态为`Sleeping`，堆栈最顶层为`java.lang.Thread.sleep(Native Method)`，并最终调用到`com.example.testapp.HeavyService.performHeavyOperation(HeavyService.java:89)`。
     - 原始内容（关键行）：
       ```
       "main" prio=5 tid=1 Sleeping
         ...
         at java.lang.Thread.sleep(Native Method)
         at java.lang.Thread.sleep(Thread.java:440)
         at java.lang.Thread.sleep(Thread.java:356)
         at com.example.testapp.HeavyService.performHeavyOperation(HeavyService.java:89)
         at com.example.testapp.HeavyService.onHandleIntent(HeavyService.java:45)
         at android.app.IntentService$ServiceHandler.handleMessage(IntentService.java:78)
         ...
       ```

2. **知识依据**：
   - 无（ANR相关诊断知识库未能加载，但根据Android开发常识，主线程执行耗时操作（如Thread.sleep）会直接导致ANR）。

3. **代码分析依据（如有）**：
   - 无（未提供源码仓库地址，但Trace已明确指向代码行`HeavyService.java:89`）。

4. **其他依据（如有）**：
   - 无

5. **因果关系**：
   - **根因**：`HeavyService.performHeavyOperation`中调用`Thread.sleep`，使主线程进入休眠。
   - **中间技术事件**：主线程被阻塞，无法处理系统事件（输入、广播、服务超时检查等）。
   - **表象问题**：系统检测到服务`com.example.testapp/.HeavyService`执行时间超过阈值（约5秒），触发ANR。
   - **时间关系**：耗时操作开始（03:34:05.428）到ANR上报（03:34:11.428）间隔约6秒，符合Android服务ANR的典型超时时间（前台服务5秒，后台服务可能更长）。

**时间线**：

| 时间              | 事件                                                                 | 来源                      |
|-------------------|----------------------------------------------------------------------|---------------------------|
| 03:34:05.428      | MainActivity记录“Performing heavy database operation”，疑似HeavyService开始执行耗时操作。 | 日志：MainActivity        |
| 03:34:11.428      | ActivityManager报告ANR，原因为“executing service com.example.testapp/.HeavyService”。 | 日志：ActivityManager     |
| 03:34:11（同一时刻） | ANR Trace捕获主线程状态为Sleeping，堆栈显示位于`HeavyService.performHeavyOperation`的sleep调用。 | Trace：Dalvik Threads     |

**进一步建议（可选）**：

- **立即修复**：检查`HeavyService.java`第89行附近的代码，确保耗时的数据库操作或任何阻塞调用不在主线程执行。若服务本应在后台工作，请确认`HeavyService`是否正确继承了`IntentService`，且`onHandleIntent`中的工作未意外切换到主线程（例如通过`runOnUiThread`或直接在主线程中启动服务）。
- **补充排查**：若问题复现，可收集更完整的系统日志（`logcat -b events`）以确认ANR前后的输入事件分发情况。
- **其他可能原因（低置信度）**：
  - 主线程可能同时被其他操作（如同步I/O、复杂计算）阻塞，但Trace中未显示其他明显阻塞点，当前证据已足够定位。
```
### 接入你自己的问题

你可以：

- 在 `examples/` 下创建自己的问题目录（包含日志、Trace、配置等）
- 在 `test_case.py` 中新增一个对应的 `issue_xxx` 文本块，指定问题描述和问题目录
- 修改 `test_case_entry` 指向你的问题，即可快速试跑

---

如果你希望将 SWEDeepDiver 集成到 CI / 问题排查平台 / 内部开发工具中，可以：

- 复用 `react_core/` + `tools/` 作为后端服务能力；
- 使用你自己的 LLM 配置与知识库；
- 利用 `preprocess/` + `app/processor.py` 接入企业内部的日志解密与脱敏规范。

## 未来规划
这是一个边学边做项目，代码层面，还有很多不完善的地方，后续逐步完善。功能层面未来规划如下：

- [ ] ProcessFile tool 增强：
  - [ ] 支持按文件类型插拔文件处理器
- [ ] 增加网络搜索能力：WebSearch tool
- [ ] 完善代码分析能力：
  - [ ] 代码库配置完善
  - [ ] Code Agent可配、可插拔
  - [ ] 提示优化
  - [ ] 远端代码库自动拉取

---

## 致谢

本项目:
- 在配置系统上参考了[OpenManus](https://github.com/FoundationAgents/OpenManus)的实践经验。
- 在提示语和工具设计上参考了[ClaudeCode](https://github.com/anthropics/claude-code)

在此对 OpenManus/ClaudeCode 项目的作者与社区表示感谢。

---

## 免责声明

1. **数据安全与合规性**
   - SWEDeepDiver 主要面向本地/自有环境使用，不会主动向项目外部传输你的日志、源码或其他数据，除非你在配置中显式选择调用第三方 LLM 服务。
   - 日志、Trace、源码等数据可能包含敏感信息（如用户隐私、业务机密、访问密钥等）。请在使用前确保：
     - 已根据公司/组织的安全规范进行必要的脱敏与访问控制；
     - 如需使用云端 LLM 服务，已评估并接受相应数据合规与风险。
   - 项目提供了 `IDataMasker` 与 `IDecryptor` 等接口，方便你在 `preprocess/` 与 `app/processor.py` 中实现自定义的脱敏与解密策略，但**如何配置与使用这些策略、是否满足你所在组织的安全要求，完全由你自行负责**。

2. **诊断结果的有限性**
   - SWEDeepDiver 依赖日志、Trace、知识库与 LLM 能力给出自动化诊断结论，这些结论：
     - 可能受限于数据缺失、知识不完整、模型能力等因素；
     - 不保证在任何场景下都完全准确或覆盖所有可能根因。
   - 本项目的输出仅作为**辅助分析工具**，不应被视为对生产系统行为的唯一判断依据。对于重要的生产事故、合规风险或高价值业务问题，仍建议由具备相应经验的工程师进行最终审核与决策。

3. **使用风险**
   - 使用本项目即表示你理解并接受：项目以 “按现状（as-is）” 方式提供，不对任何直接或间接损失（包括但不限于业务损失、数据泄露、系统不可用）承担责任。
   - 请在受控环境中逐步验证和引入本项目，避免在未充分验证前直接用于关键生产系统。
```
