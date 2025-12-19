# WebWeaver 工具调用和扩展功能

本文档介绍从 deepagents 迁移到 WebWeaver 的新功能，包括统一的工具调用框架、子智能体系统和技能系统。

## 1. 统一的工具调用框架

### 1.1 工具注册表 (ToolRegistry)

`ToolRegistry` 提供了统一的工具注册和管理机制：

```python
from webweaver.tools import ToolRegistry, ToolResult, FunctionTool

# 创建注册表
registry = ToolRegistry()

# 注册自定义工具
class MyTool(Tool):
    @property
    def name(self) -> str:
        return "my_tool"
    
    @property
    def description(self) -> str:
        return "My custom tool"
    
    def execute(self, **kwargs) -> ToolResult:
        # 执行工具逻辑
        return ToolResult(success=True, content="result")

registry.register(MyTool())

# 或注册函数作为工具
def my_function(param: str) -> str:
    return f"Processed: {param}"

registry.register_function(
    name="my_function",
    func=my_function,
    description="Process a parameter",
)
```

### 1.2 工具执行器 (ToolExecutor)

`ToolExecutor` 负责解析和执行工具调用：

```python
from webweaver.tools import ToolExecutor, get_registry

executor = ToolExecutor(registry=get_registry())

# 解析工具调用
agent_output = '<tool_call>{"name": "http_request", "arguments": {"url": "https://api.example.com"}}</tool_call>'
tool_calls = executor.parse_tool_calls(agent_output)

# 执行工具调用
results = executor.execute_tool_calls(agent_output)
for result in results:
    print(result.formatted_response)
```

## 2. 扩展工具

WebWeaver 现在包含以下扩展工具：

### 2.1 HTTP 请求工具

```python
from webweaver.tools.extended_tools import http_request

result = http_request(
    url="https://api.example.com/data",
    method="POST",
    data={"key": "value"},
    headers={"Authorization": "Bearer token"},
)
```

### 2.2 代码执行工具

```python
from webweaver.tools.extended_tools import execute_code

result = execute_code(
    code="print('Hello, World!')",
    language="python",
    timeout=30,
)
```

### 2.3 文件操作工具

```python
from webweaver.tools.extended_tools import read_file, write_file, list_directory

# 读取文件
result = read_file("path/to/file.txt")

# 写入文件
result = write_file("path/to/file.txt", "content")

# 列出目录
result = list_directory(".", pattern="*.py")
```

## 3. 子智能体系统 (SubAgent)

子智能体系统允许主智能体将复杂任务委托给专门的子智能体：

```python
from webweaver.agents.subagent import SubAgentConfig, SubAgentManager
from webweaver.llm.client import LLMClient
from webweaver.tools import get_registry

# 创建子智能体管理器
llm = LLMClient(settings)
manager = SubAgentManager(llm=llm, tool_registry=get_registry())

# 注册子智能体
config = SubAgentConfig(
    name="researcher",
    description="Specialized agent for research tasks",
    system_prompt="You are a research assistant...",
)
manager.register_subagent(config)

# 创建任务工具
from webweaver.agents.subagent import create_task_tool
create_task_tool(manager)

# 现在可以在工具调用中使用 task 工具
# <tool_call>{"name": "task", "arguments": {"description": "Research topic X", "subagent_type": "researcher"}}</tool_call>
```

## 4. 技能系统 (Skills)

技能系统实现了渐进式披露模式，允许智能体发现和使用专业技能：

### 4.1 创建技能

创建技能目录结构：

```
~/.webweaver/skills/
└── web-research/
    ├── SKILL.md
    └── helper.py
```

`SKILL.md` 文件格式：

```markdown
---
name: web-research
description: Structured approach to conducting thorough web research
---

# Web Research Skill

## When to Use
- User asks you to research a topic
- Need to gather information from multiple sources

## Workflow
1. Identify key search queries
2. Search multiple sources
3. Synthesize findings
...
```

### 4.2 使用技能中间件

```python
from webweaver.skills.middleware import SkillsMiddleware

middleware = SkillsMiddleware(
    skills_dir="~/.webweaver/skills",
    project_skills_dir="./.webweaver/skills",
)

# 获取技能提示词（添加到系统提示词）
skills_prompt = middleware.get_skills_prompt()

# 列出可用技能
skills = middleware.list_available_skills()
```

## 5. 集成示例

完整的集成示例：

```python
from webweaver.config import Settings, load_settings
from webweaver.llm.client import LLMClient
from webweaver.tools import setup_tools_for_agent
from webweaver.tools.integration import setup_skills_middleware
from webweaver.agents.subagent import SubAgentManager, SubAgentConfig, create_task_tool

# 加载设置
settings = load_settings()

# 设置工具
registry = setup_tools_for_agent(settings, enable_extended_tools=True)

# 设置技能
skills_middleware = setup_skills_middleware(
    skills_dir="~/.webweaver/skills",
)

# 设置子智能体
llm = LLMClient(settings)
subagent_manager = SubAgentManager(llm=llm, tool_registry=registry)

# 注册子智能体
researcher_config = SubAgentConfig(
    name="researcher",
    description="Conducts thorough research on topics",
    system_prompt="You are a research assistant...",
)
subagent_manager.register_subagent(researcher_config)

create_task_tool(subagent_manager)

# 现在可以在 Planner 或 Writer 中使用这些工具
```

## 6. 工具审批机制

工具执行可以配置为需要审批：

```python
def approval_callback(tool_name: str, arguments: dict) -> bool:
    """用户审批回调"""
    print(f"Tool: {tool_name}")
    print(f"Arguments: {arguments}")
    response = input("Approve? (y/n): ")
    return response.lower() == "y"

result = registry.execute(
    "execute_code",
    {"code": "rm -rf /", "language": "bash"},
    require_approval=True,
    approval_callback=approval_callback,
)
```

## 7. 与现有代码的兼容性

新的工具系统与现有的 WebWeaver 代码完全兼容。现有的 `search` 和 `retrieve` 工具可以继续使用，同时可以添加新的工具。

Planner 和 Writer Agent 可以逐步迁移到使用新的工具系统，而不会破坏现有功能。

